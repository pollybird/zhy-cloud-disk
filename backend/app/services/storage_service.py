"""物理文件存储服务：UUID 物理文件名、分用户目录、流式落盘、安全路径。

1.2.0 起新增两类目录：
- blobs/                 内容寻址块：blobs/<hash前2位>/<hash>，跨用户共享
- tmp/uploads/<uuid>/    分片上传暂存：<index>.part
- tmp/staging/           分片合并/秒传校验用的暂存文件
"""
import hashlib
import os
import shutil
import uuid
from pathlib import Path

from flask import current_app

from ..utils.errors import ApiError

CHUNK_SIZE = 1024 * 1024  # 1MB 分块


def storage_root() -> Path:
    root = Path(current_app.config["STORAGE_DIR"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def user_dir(user_id: int) -> Path:
    path = (storage_root() / str(int(user_id))).resolve()
    # 防穿越：必须位于存储根内
    if not _is_within(storage_root(), path):
        raise ApiError("非法的存储路径", code=3001)
    path.mkdir(parents=True, exist_ok=True)
    return path


def extract_suffix(filename: str) -> str:
    """提取小写后缀（不带点），无后缀返回空串。"""
    if not filename or "." not in filename:
        return ""
    suffix = filename.rsplit(".", 1)[1].strip().lower()
    return suffix[:32]


def physical_name(suffix: str) -> str:
    name = uuid.uuid4().hex
    return f"{name}.{suffix}" if suffix else name


def safe_original_name(filename: str) -> str:
    """校验用户文件名：仅取基名防穿越，清理控制符与非法字符，保留中文。"""
    filename = (filename or "").replace("\\", "/").split("/")[-1]
    # 清理控制字符与文件系统非法字符（U+0000-U+001F、/ \\ : * ? " < > |）
    cleaned = "".join(
        ch
        for ch in filename
        if ord(ch) >= 32 and ch not in '/\\:*?"<>|'
    ).strip(" .")
    if not cleaned or cleaned in {".", ".."}:
        raise ApiError("文件名不合法", code=3002)
    return cleaned[:255]


def save_stream(file_storage, user_id: int) -> tuple[str, str, int]:
    """将上传流分块写入磁盘。

    返回 (save_path, suffix, size)；文件名使用 UUID 防覆盖。
    """
    original = safe_original_name(file_storage.filename)
    suffix = extract_suffix(original)
    target_dir = user_dir(user_id)
    target = target_dir / physical_name(suffix)
    size = 0
    try:
        with open(target, "wb") as f:
            while True:
                chunk = file_storage.stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                f.write(chunk)
    except OSError as e:
        remove_physical(str(target))
        raise ApiError(f"文件保存失败：{e}", code=3003)
    return str(target), suffix, size


def department_dir(dept_id: int) -> Path:
    path = (storage_root() / "dept" / str(int(dept_id))).resolve()
    if not _is_within(storage_root(), path):
        raise ApiError("非法的存储路径", code=3001)
    path.mkdir(parents=True, exist_ok=True)
    return path


# ------------------------------------------------------------------
# 1.2.0 内容寻址 blob 存储
# ------------------------------------------------------------------

def blobs_root() -> Path:
    path = (storage_root() / "blobs").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def blob_path(file_hash: str) -> Path:
    """内容寻址目标路径：blobs/<hash前2位>/<hash全名>。"""
    h = (file_hash or "").strip().lower()
    if len(h) != 32 or not all(c in "0123456789abcdef" for c in h):
        raise ApiError("非法的文件指纹", code=3006)
    path = (blobs_root() / h[:2] / h).resolve()
    if not _is_within(blobs_root(), path):
        raise ApiError("非法的存储路径", code=3001)
    return path


def is_blob_path(save_path: str | None) -> bool:
    """判断物理路径是否属于 blob 存储（1.2.0 去重文件）。"""
    if not save_path:
        return False
    try:
        Path(save_path).resolve().relative_to(blobs_root())
        return True
    except (ValueError, OSError):
        return False


def _tmp_root() -> Path:
    path = (storage_root() / "tmp").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def staging_dir() -> Path:
    path = (_tmp_root() / "staging").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_staging_path() -> Path:
    return staging_dir() / uuid.uuid4().hex


def save_staged_stream(file_storage) -> tuple[str, int, str]:
    """整文件上传先落暂存区并增量算 MD5，返回 (path, size, md5_hex)。

    暂存文件随后由 blob_service 决定移入 blob 目录或丢弃。
    """
    safe_original_name(file_storage.filename)  # 仅做文件名合法性校验
    target = new_staging_path()
    size = 0
    h = hashlib.md5()
    try:
        with open(target, "wb") as f:
            while True:
                chunk = file_storage.stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                f.write(chunk)
                h.update(chunk)
    except OSError as e:
        remove_physical(str(target))
        raise ApiError(f"文件保存失败：{e}", code=3003)
    return str(target), size, h.hexdigest()


# ------------------------------------------------------------------
# 1.2.0 分片上传暂存
# ------------------------------------------------------------------

def uploads_tmp_root() -> Path:
    path = (_tmp_root() / "uploads").resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_dir(upload_id: str) -> Path:
    """分片会话目录（upload_id 为 uuid，严格校验防穿越）。"""
    token = (upload_id or "").strip()
    try:
        uuid.UUID(token)
    except (ValueError, AttributeError):
        raise ApiError("非法的上传会话标识", code=3207)
    path = (uploads_tmp_root() / token).resolve()
    if not _is_within(uploads_tmp_root(), path):
        raise ApiError("非法的存储路径", code=3001)
    return path


def part_path(upload_id: str, index: int) -> Path:
    path = (session_dir(upload_id) / f"{int(index):08d}.part").resolve()
    if not _is_within(session_dir(upload_id), path):
        raise ApiError("非法的存储路径", code=3001)
    return path


def save_part(file_storage, upload_id: str, index: int) -> tuple[int, str]:
    """写入单个分片到会话目录，返回 (size, md5_hex)。重复序号覆盖旧分片。"""
    target_dir = session_dir(upload_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = part_path(upload_id, index)
    size = 0
    h = hashlib.md5()
    try:
        with open(target, "wb") as f:
            while True:
                chunk = file_storage.stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                f.write(chunk)
                h.update(chunk)
    except OSError as e:
        remove_physical(str(target))
        raise ApiError(f"分片保存失败：{e}", code=3003)
    return size, h.hexdigest()


def merge_parts(upload_id: str, indexes: list[int]) -> tuple[str, int, str]:
    """按序号顺序合并分片到暂存文件，流式计算整体 MD5。

    返回 (staged_path, total_size, md5_hex)；调用方负责后续移动或删除。
    """
    target = new_staging_path()
    total = 0
    h = hashlib.md5()
    try:
        with open(target, "wb") as out:
            for idx in indexes:
                src = part_path(upload_id, idx)
                if not src.is_file():
                    raise ApiError(f"分片 {idx} 缺失，无法合并", code=3210)
                with open(src, "rb") as f:
                    while True:
                        chunk = f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        total += len(chunk)
                        out.write(chunk)
                        h.update(chunk)
    except ApiError:
        remove_physical(str(target))
        raise
    except OSError as e:
        remove_physical(str(target))
        raise ApiError(f"分片合并失败：{e}", code=3003)
    return str(target), total, h.hexdigest()


def remove_session_dir(upload_id: str) -> None:
    try:
        path = session_dir(upload_id)
    except ApiError:
        return
    shutil.rmtree(path, ignore_errors=True)


def remove_staging(path: str) -> None:
    try:
        p = Path(path).resolve()
        if _is_within(staging_dir(), p) and p.is_file():
            p.unlink()
    except OSError:
        pass


def iter_session_dirs() -> list[str]:
    """列出磁盘上现存的全部分片会话目录名（供孤儿目录 GC）。"""
    root = uploads_tmp_root()
    return [p.name for p in root.iterdir() if p.is_dir()] if root.exists() else []


def open_physical(save_path: str) -> Path:
    """校验物理路径安全并返回 Path（不检查存在性）。"""
    if not save_path:
        raise ApiError("文件路径缺失", code=3004)
    path = Path(save_path).resolve()
    if not _is_within(storage_root(), path):
        raise ApiError("非法的文件访问路径", code=3005)
    return path


def remove_physical(save_path: str) -> bool:
    try:
        path = Path(save_path).resolve()
        if _is_within(storage_root(), path) and path.is_file():
            path.unlink()
            return True
    except OSError:
        return False
    return False


def _is_within(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
