"""存量文件收敛与 blob 对账（每日低峰执行）。

1. 为 1.0/1.1 无 file_hash 的正常文件流式补算 MD5（每轮限量）
2. 把非 blob 路径的物理文件按 hash+size 归组并入 blob 存储：
   同内容多份物理副本只保留一份，FileNode 改指 blob，旧副本删除
3. 对账：ref_count 与「指向该 blob 物理路径的正常节点数」对齐；归零清除
4. 清理 blobs 目录下无 DB 行的孤儿物理文件（异常回滚残留）

全程幂等、可中断；物理删除均在 DB 提交之后。
"""
import hashlib
import os
from collections import defaultdict
from pathlib import Path

from ..extensions import db
from ..models.file_blob import FileBlob
from ..models.file_node import FileNode
from ..services import storage_service
from ..services.blob_service import normalize_hash

HASH_BATCH = 10        # 每轮最多补算 hash 的文件数
ADOPT_BATCH = 100      # 每轮最多归并的 hash 组数
HASH_READ = 1024 * 1024


def _backfill_missing_hash() -> int:
    nodes = (
        db.session.query(FileNode)
        .filter(
            FileNode.is_folder.is_(False),
            FileNode.status == "normal",
            FileNode.save_path.isnot(None),
            FileNode.file_hash.is_(None),
        )
        .limit(HASH_BATCH)
        .all()
    )
    done = 0
    for node in nodes:
        try:
            path = storage_service.open_physical(node.save_path)
            if not path.is_file():
                continue
            h = hashlib.md5()
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(HASH_READ)
                    if not chunk:
                        break
                    h.update(chunk)
            node.file_hash = h.hexdigest()
            done += 1
        except Exception:
            db.session.rollback()
            continue
    if done:
        db.session.commit()
    return done


def _adopt_groups() -> int:
    """归并非 blob 路径节点，返回处理的组数。"""
    nodes = (
        db.session.query(FileNode)
        .filter(
            FileNode.is_folder.is_(False),
            FileNode.status == "normal",
            FileNode.save_path.isnot(None),
            FileNode.file_hash.isnot(None),
        )
        .all()
    )
    groups: dict[tuple[str, int], list[FileNode]] = defaultdict(list)
    for n in nodes:
        if storage_service.is_blob_path(n.save_path):
            continue
        h = normalize_hash(n.file_hash)
        if h:
            groups[(h, int(n.file_size))].append(n)

    processed = 0
    for (h, size), members in list(groups.items())[:ADOPT_BATCH]:
        try:
            _merge_group(h, size, members)
            processed += 1
        except Exception:
            db.session.rollback()
            continue
    return processed


def _merge_group(h: str, size: int, members: list[FileNode]) -> None:
    blob = db.session.query(FileBlob).filter(FileBlob.file_hash == h).first()
    target: Path | None = None
    to_unlink: list[str] = []

    if blob is not None:
        if int(blob.file_size) != size:
            return
        target = storage_service.open_physical(blob.save_path)
        if not target.is_file():
            donor = _first_existing(members, target)
            if donor is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(donor, target)
    else:
        donor_path = _first_existing(members, None)
        if donor_path is None:
            return
        target = storage_service.blob_path(h)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(donor_path, target)
        blob = FileBlob(
            file_hash=h, file_size=size, save_path=str(target), ref_count=0
        )
        db.session.add(blob)
        db.session.flush()

    for n in members:
        current = storage_service.open_physical(n.save_path)
        if current != target:
            if current.is_file():
                to_unlink.append(str(current))
            n.save_path = str(target)
    db.session.commit()
    for p in to_unlink:
        storage_service.remove_physical(p)


def _first_existing(members: list[FileNode], exclude: Path | None) -> str | None:
    for n in members:
        try:
            p = storage_service.open_physical(n.save_path)
        except Exception:
            continue
        if p.is_file() and p != exclude:
            return str(p)
    return None


def _reconcile() -> dict:
    fixed = deleted = 0
    blobs = db.session.query(FileBlob).all()
    for blob in list(blobs):
        actual = (
            db.session.query(db.func.count(FileNode.id))
            .filter(
                FileNode.status == "normal",
                FileNode.is_folder.is_(False),
                FileNode.file_hash == blob.file_hash,
                FileNode.save_path == blob.save_path,
            )
            .scalar()
        )
        if not actual:
            path = blob.save_path
            db.session.delete(blob)
            db.session.commit()
            storage_service.remove_physical(path)
            deleted += 1
        elif actual != blob.ref_count:
            blob.ref_count = actual
            fixed += 1
    if fixed:
        db.session.commit()
    return {"refcount_fixed": fixed, "zero_ref_removed": deleted}


def _sweep_orphan_blobs() -> int:
    known = {
        storage_service.open_physical(save_path)
        for (save_path,) in db.session.query(FileBlob.save_path).all()
    }
    removed = 0
    root = storage_service.blobs_root()
    for path in root.glob("*/*"):
        if not path.is_file() or path in known:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def run() -> dict:
    hashed = _backfill_missing_hash()
    merged = _adopt_groups()
    recon = _reconcile()
    orphans = _sweep_orphan_blobs()
    return {
        "hash_backfilled": hashed,
        "groups_merged": merged,
        **recon,
        "orphan_blobs_removed": orphans,
    }
