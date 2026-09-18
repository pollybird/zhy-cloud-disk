"""内容寻址块（blob）服务：全局去重注册与引用计数。

- get_or_create：新内容暂存文件转 blob；同 hash+size 已存在则复用（跨用户秒传基础）
- retain / release：引用计数增减；归零时由调用方在事务提交后删除物理文件
- find_usable：秒传命中查询（hash+size 双匹配且物理文件存在）

调用约定：本模块只在当前 DB 事务内 flush，不主动 commit；
release 返回需删除的物理路径，由调用方 commit 成功后再 unlink。
"""
import os

from sqlalchemy import and_, update
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models.file_blob import FileBlob
from ..utils.errors import ApiError
from . import storage_service


def _normalize(file_hash: str) -> str:
    h = normalize_hash(file_hash)
    if h is None:
        raise ApiError("非法的文件指纹", code=3206)
    return h


def normalize_hash(file_hash: str) -> str | None:
    """返回小写 32 位 MD5；非法返回 None。"""
    h = (file_hash or "").strip().lower()
    if len(h) == 32 and all(c in "0123456789abcdef" for c in h):
        return h
    return None


def find_usable(file_hash: str, file_size: int) -> FileBlob | None:
    """秒传命中：按 hash 查 blob，size 必须一致且物理文件存在。"""
    try:
        h = _normalize(file_hash)
    except ApiError:
        return None
    blob = db.session.query(FileBlob).filter(FileBlob.file_hash == h).first()
    if blob is None:
        return None
    if int(blob.file_size) != int(file_size):
        return None
    try:
        if not storage_service.open_physical(blob.save_path).is_file():
            return None
    except ApiError:
        return None
    return blob


def get_or_create(file_hash: str, file_size: int, staged_path: str) -> FileBlob:
    """暂存文件转 blob。

    返回 blob（不调整计数，调用方需 retain）。
    已存在同 hash blob：校验 size，复用 blob，丢弃暂存；
    物理文件缺失时用本次暂存原地补回。
    """
    h = _normalize(file_hash)
    size = int(file_size)

    existing = db.session.query(FileBlob).filter(FileBlob.file_hash == h).first()
    if existing is not None:
        if int(existing.file_size) != size:
            raise ApiError("文件指纹与大小不匹配", code=3205)
        path = storage_service.open_physical(existing.save_path)
        if path.is_file():
            storage_service.remove_staging(staged_path)
        else:
            # 物理文件丢失修复：同卷移入原路径
            path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_path, path)
        return existing

    target = storage_service.blob_path(h)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        # 事务回滚遗留或并发写入的同内容物理块：直接引用，丢弃暂存
        storage_service.remove_staging(staged_path)
    else:
        # 内容相同则字节一致：并发场景下覆盖同名目标也安全
        os.replace(staged_path, target)

    blob = FileBlob(
        file_hash=h, file_size=size, save_path=str(target), ref_count=0
    )
    db.session.add(blob)
    try:
        db.session.flush()
    except IntegrityError:
        # 并发：另一事务已插入同 hash blob，回滚到保存点后复用
        db.session.rollback()
        winner = db.session.query(FileBlob).filter(FileBlob.file_hash == h).first()
        if winner is None:
            raise ApiError("文件去重注册失败，请重试", code=3211)
        return winner
    return blob


def retain(blob: FileBlob) -> None:
    """引用数 +1（原子 UPDATE，保证并发计数正确）。"""
    db.session.execute(
        update(FileBlob)
        .where(FileBlob.id == blob.id)
        .values(ref_count=FileBlob.ref_count + 1)
    )
    db.session.refresh(blob)


def release(blob: FileBlob) -> str | None:
    """引用数 -1；归零则删除 blob 行并返回待删物理路径（调用方 commit 后 unlink）。"""
    result = db.session.execute(
        update(FileBlob)
        .where(and_(FileBlob.id == blob.id, FileBlob.ref_count > 0))
        .values(ref_count=FileBlob.ref_count - 1)
    )
    if result.rowcount == 0:
        # 计数已为 0 等异常状态：仅记录，不重复删除
        return None
    db.session.refresh(blob)
    if blob.ref_count <= 0:
        path = blob.save_path
        db.session.delete(blob)
        return path
    return None


def release_for_hash(
    file_hash: str | None, save_path: str | None
) -> tuple[str, str | None]:
    """按节点信息释放一次引用。

    返回 (kind, path)：
    - ("legacy", None)  非 blob 路径（1.0/1.1 旧文件），调用方直接删 save_path
    - ("alive", None)   blob 仍有其他引用，物理文件保留
    - ("removed", path) 引用归零，调用方在提交后删除 path
    - ("missing", None) blob 路径但无记录（异常漂移），保守不删
    """
    if not storage_service.is_blob_path(save_path):
        return "legacy", None
    h = normalize_hash(file_hash) if file_hash else None
    if h is None:
        return "missing", None
    blob = db.session.query(FileBlob).filter(FileBlob.file_hash == h).first()
    if blob is None:
        return "missing", None
    removed_path = release(blob)
    if removed_path is not None:
        return "removed", removed_path
    return "alive", None
