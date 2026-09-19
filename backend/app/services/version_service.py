"""文件历史版本服务（1.3.0）。

引用计数约定（与 blob_service 配合）：
- FileNode 正常内容持有 1 次 blob 引用；每个 FileVersion 同样持有 1 次。
- 覆盖归档：旧内容的引用从节点「转移」给版本行，总数不变（不 retain/release）。
- 版本淘汰/节点彻底删除：释放对应引用，归零才删物理文件。
- legacy 物理文件（1.0/1.1，非 blob 目录）由版本独占原路径，淘汰时直接删除。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from ..extensions import db
from ..models.file_node import FileNode
from ..models.file_version import FileVersion
from ..models.user import User
from ..utils.errors import ApiError
from . import blob_service, permission_service, setting_service, storage_service

VERSION_DISABLED_CODE = 3510


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _next_version_no(node_id: int) -> int:
    current = (
        db.session.query(func.max(FileVersion.version_no))
        .filter(FileVersion.node_id == node_id)
        .scalar()
    )
    return (current or 0) + 1


def archive_version(node: FileNode, operator_id: int | None) -> FileVersion | None:
    """把节点当前内容归档为一个历史版本（引用转移，不调整 blob 计数）。

    旧数据无 save_path（理论上文件节点都有）则跳过；调用方负责仅在
    version_enabled 且新旧 hash 不同（或旧内容为 legacy）时调用。
    """
    if not node.save_path:
        return None
    version = FileVersion(
        node_id=node.id,
        version_no=_next_version_no(node.id),
        file_hash=node.file_hash,
        file_size=int(node.file_size or 0),
        save_path=node.save_path,
        operator_id=operator_id,
        create_time=_utcnow(),
    )
    db.session.add(version)
    db.session.flush()
    return version


def prune_versions(node_id: int) -> list[str]:
    """按保留数量与天数淘汰旧版本，返回待删物理路径（调用方 commit 后 unlink）。"""
    max_count, retention_days = setting_service.get_version_policy()
    cutoff = _utcnow() - timedelta(days=retention_days)

    to_unlink: list[str] = []

    # 1) 超期版本
    expired = (
        db.session.query(FileVersion)
        .filter(FileVersion.node_id == node_id, FileVersion.create_time < cutoff)
        .all()
    )
    for v in expired:
        _release_version(v, to_unlink)

    # 2) 超量版本（保留 version_no 最大的 max_count 个）
    survivors = (
        db.session.query(FileVersion.id)
        .filter(FileVersion.node_id == node_id)
        .order_by(FileVersion.version_no.desc())
        .limit(max_count)
        .subquery()
    )
    overflow = (
        db.session.query(FileVersion)
        .filter(
            FileVersion.node_id == node_id,
            FileVersion.id.notin_(db.session.query(survivors.c.id)),
        )
        .all()
    )
    for v in overflow:
        _release_version(v, to_unlink)

    return to_unlink


def _release_version(version: FileVersion, to_unlink: list[str]) -> None:
    kind, released_path = blob_service.release_for_hash(
        version.file_hash, version.save_path
    )
    if kind == "removed" and released_path:
        to_unlink.append(released_path)
    elif kind == "legacy" and version.save_path:
        to_unlink.append(version.save_path)
    db.session.delete(version)


def release_all_versions(node_id: int) -> list[str]:
    """彻底删除节点时释放其全部历史版本，返回待删物理路径。"""
    versions = (
        db.session.query(FileVersion)
        .filter(FileVersion.node_id == node_id)
        .all()
    )
    to_unlink: list[str] = []
    for v in versions:
        _release_version(v, to_unlink)
    return to_unlink


def list_versions(node: FileNode) -> list[dict]:
    rows = (
        db.session.query(FileVersion, User.username)
        .outerjoin(User, User.id == FileVersion.operator_id)
        .filter(FileVersion.node_id == node.id)
        .order_by(FileVersion.version_no.desc())
        .all()
    )
    result = []
    for v, username in rows:
        item = v.to_dict()
        item["operator_name"] = username
        result.append(item)
    return result


def get_version_for_access(
    user: User, version_id: int, required: str = "read"
) -> tuple[FileVersion, FileNode]:
    version = db.session.get(FileVersion, int(version_id))
    if version is None:
        raise ApiError("历史版本不存在", code=3511, http_status=404)
    node = db.session.get(FileNode, version.node_id)
    if node is None or node.status != "normal":
        raise ApiError("原文件不存在或已删除", code=3511, http_status=404)
    if node.department_id is not None:
        if not permission_service.check_file_access(user, node, required):
            raise ApiError("无权访问该文件", code=4032, http_status=403)
        if required in ("write", "delete"):
            from . import file_lock_service

            file_lock_service.ensure_unlocked(user, node)
    elif node.user_id != user.id:
        raise ApiError("历史版本不存在", code=3511, http_status=404)
    return version, node


def restore_version(user: User, version_id: int) -> FileNode:
    """恢复指定版本：当前内容先归档为新版本，再与目标版本交换指向（计数净零）。"""
    if not setting_service.is_version_enabled():
        raise ApiError("历史版本功能已关闭，无法恢复版本", code=VERSION_DISABLED_CODE)

    version, node = get_version_for_access(user, version_id, required="write")
    if not node.save_path:
        raise ApiError("文件内容缺失，无法恢复", code=3512)

    target_hash = version.file_hash
    target_path = version.save_path
    target_size = int(version.file_size or 0)

    try:
        # 1) 当前内容归档（引用由节点转移给新版本行）
        archive_version(node, user.id)

        # 2) 节点指向目标版本内容（引用由版本行转移给节点）
        node.file_hash = target_hash
        node.save_path = target_path
        node.file_size = target_size
        node.upload_time = _utcnow()
        db.session.delete(version)
        db.session.flush()

        # 3) 归档可能造成超量/超期，淘汰之（恢复的目标版本已删行，不会被淘汰）
        to_unlink = prune_versions(node.id)
        db.session.commit()
    except ApiError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        raise

    for path in to_unlink:
        storage_service.remove_physical(path)

    if node.department_id:
        from .file_service import _log_dept_file_op

        _log_dept_file_op(user, "file_restore_version", node, {"version_id": version_id})
    return node
