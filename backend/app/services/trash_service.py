"""回收站服务（1.3.0）。

软删：节点子树置 deleted、根节点改名释放唯一约束、写 TrashItem；
      不释放 blob、不退配额、不删物理文件。
硬删：释放节点与全部历史版本的 blob 引用、删除行、退配额、提交后删物理文件。
还原：子树复位、原名恢复（冲突自动改名）、原父缺失则回到根目录。
"""
from datetime import datetime, timedelta, timezone

from ..extensions import db
from ..models.department import Department
from ..models.file_lock import FileLock
from ..models.file_node import FileNode
from ..models.trash_item import TrashItem
from ..models.user import User
from ..utils.errors import ApiError
from . import (
    blob_service,
    permission_service,
    setting_service,
    storage_service,
    version_service,
)

TRASH_NAME_PREFIX = "#trash"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def trash_token(node_id: int) -> str:
    return f"{TRASH_NAME_PREFIX}{node_id}"


# ---------------------------------------------------------------------------
# 子树收集（不限 status：软删前全 normal，硬删时全 deleted）
# ---------------------------------------------------------------------------

def collect_subtree_ids(root_id: int) -> set[int]:
    ids = {root_id}
    frontier = [root_id]
    while frontier:
        children = [
            row[0]
            for row in db.session.query(FileNode.id)
            .filter(FileNode.parent_id.in_(frontier))
            .all()
        ]
        if not children:
            break
        ids.update(children)
        frontier = children
    return ids


def _file_nodes_in(ids: set[int]) -> list[FileNode]:
    if not ids:
        return []
    return (
        db.session.query(FileNode)
        .filter(FileNode.id.in_(ids), FileNode.is_folder.is_(False))
        .all()
    )


def func_greatest_zero(expr):
    """兼容 SQLite/MySQL 的 max(value, 0)。"""
    from sqlalchemy import case, literal

    return case((expr < 0, literal(0)), else_=expr)


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------

def check_trash_access(user: User, item: TrashItem) -> None:
    if item.department_id:
        if not permission_service.check_department_access(
            user, item.department_id, "delete"
        ):
            raise ApiError("无权操作该部门的回收站", code=4032, http_status=403)
    elif item.owner_user_id != user.id:
        raise ApiError("回收站条目不存在", code=3520, http_status=404)


# ---------------------------------------------------------------------------
# 软删除
# ---------------------------------------------------------------------------

def soft_delete(user: User, node: FileNode) -> TrashItem:
    """把节点（及子树）移入回收站。调用前已完成节点级权限/锁校验。"""
    ids = collect_subtree_ids(node.id)
    file_nodes = _file_nodes_in(ids)

    # 部门文件夹：子树内任意文件正被编辑锁定则整体拒绝
    if node.is_folder and node.department_id:
        from . import file_lock_service

        file_lock_service.assert_no_lock_in_tree([f.id for f in file_nodes])

    total_size = sum(int(f.file_size or 0) for f in file_nodes)
    now = _utcnow()
    expire = now + timedelta(days=setting_service.get_trash_retention_days())
    original_name = node.file_name

    db.session.query(FileNode).filter(FileNode.id.in_(ids)).update(
        {
            FileNode.status: "deleted",
            FileNode.deleted_time: now,
            FileNode.delete_operator_id: user.id,
        },
        synchronize_session=False,
    )
    # 根节点改名释放 (user_id,parent_id,file_name) 唯一约束占用
    node.file_name = trash_token(node.id)

    item = TrashItem(
        node_id=node.id,
        original_name=original_name,
        original_parent_id=node.parent_id,
        owner_user_id=node.user_id,
        department_id=node.department_id,
        is_folder=node.is_folder,
        total_size=total_size,
        operator_id=user.id,
        create_time=now,
        expire_time=expire,
    )
    db.session.add(item)

    # 清理子树可能残留的过期锁行（活跃锁已在上面的检查中拦截）
    db.session.query(FileLock).filter(FileLock.node_id.in_(ids)).delete(
        synchronize_session=False
    )

    db.session.commit()

    if node.department_id:
        from .file_service import _log_dept_file_op

        _log_dept_file_op(
            user, "file_delete", node,
            {"trash": True, "size": total_size, "deleted_count": len(ids)},
        )
    return item


# ---------------------------------------------------------------------------
# 彻底删除
# ---------------------------------------------------------------------------

def hard_delete(node: FileNode, actor_id: int | None = None) -> int:
    """彻底删除节点子树（含全部历史版本），释放 blob 与配额，返回释放字节数。"""
    item = (
        db.session.query(TrashItem)
        .filter(TrashItem.node_id == node.id)
        .first()
    )
    ids = collect_subtree_ids(node.id)
    file_nodes = _file_nodes_in(ids)

    to_unlink: list[str] = []
    freed_space = 0
    for f in file_nodes:
        # 1) 历史版本各自释放一次引用
        to_unlink.extend(version_service.release_all_versions(f.id))
        # 2) 节点当前内容释放一次引用
        kind, released_path = blob_service.release_for_hash(f.file_hash, f.save_path)
        if kind == "removed" and released_path:
            to_unlink.append(released_path)
        elif kind == "legacy" and f.save_path:
            to_unlink.append(f.save_path)
        freed_space += int(f.file_size or 0)

    db.session.query(FileLock).filter(FileLock.node_id.in_(ids)).delete(
        synchronize_session=False
    )
    db.session.query(FileNode).filter(FileNode.id.in_(ids)).delete(
        synchronize_session=False
    )
    if item is not None:
        db.session.delete(item)

    dept_id = node.department_id
    if dept_id:
        if freed_space:
            db.session.query(Department).filter(Department.id == dept_id).update(
                {Department.used_storage: func_greatest_zero(Department.used_storage - freed_space)},
                synchronize_session=False,
            )
    else:
        if freed_space:
            db.session.query(User).filter(User.id == node.user_id).update(
                {User.used_storage: func_greatest_zero(User.used_storage - freed_space)},
                synchronize_session=False,
            )

    db.session.commit()

    for path in to_unlink:
        storage_service.remove_physical(path)

    return freed_space


# ---------------------------------------------------------------------------
# 回收站列表 / 清空 / 单条硬删
# ---------------------------------------------------------------------------

def list_trash(
    user: User, scope: str, department_id: int | None = None
) -> list[dict]:
    query = (
        db.session.query(TrashItem, User.username)
        .outerjoin(User, User.id == TrashItem.operator_id)
    )
    if scope == "department":
        if not department_id:
            raise ApiError("缺少部门参数", code=3301)
        if not permission_service.check_department_access(
            user, int(department_id), "delete"
        ):
            raise ApiError("无权查看该部门的回收站", code=4032, http_status=403)
        query = query.filter(TrashItem.department_id == int(department_id))
    else:
        query = query.filter(
            TrashItem.owner_user_id == user.id,
            TrashItem.department_id.is_(None),
        )

    result = []
    for item, operator_name in query.order_by(TrashItem.create_time.desc()).all():
        data = item.to_dict()
        data["operator_name"] = operator_name
        result.append(data)
    return result


def purge_item(user: User, trash_id: int) -> None:
    item = db.session.get(TrashItem, int(trash_id))
    if item is None:
        raise ApiError("回收站条目不存在", code=3520, http_status=404)
    check_trash_access(user, item)
    node = db.session.get(FileNode, item.node_id)
    if node is None:
        db.session.delete(item)
        db.session.commit()
        return
    hard_delete(node, user.id)


def empty_trash(
    user: User, scope: str, department_id: int | None = None
) -> int:
    if scope == "department":
        if not department_id:
            raise ApiError("缺少部门参数", code=3301)
        dept_id = int(department_id)
        if not permission_service.check_department_access(user, dept_id, "delete"):
            raise ApiError("无权清空该部门的回收站", code=4032, http_status=403)
        items = db.session.query(TrashItem).filter(
            TrashItem.department_id == dept_id
        ).all()
    else:
        items = db.session.query(TrashItem).filter(
            TrashItem.owner_user_id == user.id,
            TrashItem.department_id.is_(None),
        ).all()

    count = 0
    for item in items:
        node = db.session.get(FileNode, item.node_id)
        if node is None:
            db.session.delete(item)
            db.session.commit()
            count += 1
            continue
        hard_delete(node, user.id)
        count += 1
    return count


# ---------------------------------------------------------------------------
# 还原
# ---------------------------------------------------------------------------

def _unique_restore_name(
    user_id: int, parent_id: int | None, department_id: int | None, name: str,
    exclude_id: int,
) -> str:
    """同级 normal 空间同名冲突时追加 (1)/(2)…。"""
    if not _name_exists(user_id, parent_id, department_id, name, exclude_id):
        return name
    if "." in name:
        idx = name.rfind(".")
        stem, suffix = name[:idx], name[idx:]
    else:
        stem, suffix = name, ""
    for i in range(1, 1000):
        candidate = f"{stem} ({i}){suffix}"
        if not _name_exists(user_id, parent_id, department_id, candidate, exclude_id):
            return candidate
    raise ApiError("无法还原：同名文件过多", code=3521, http_status=409)


def _name_exists(user_id, parent_id, department_id, name, exclude_id) -> bool:
    query = db.session.query(FileNode.id).filter(
        FileNode.file_name == name,
        FileNode.status == "normal",
        FileNode.id != exclude_id,
    )
    if department_id:
        query = query.filter(FileNode.department_id == department_id)
    else:
        query = query.filter(
            FileNode.user_id == user_id, FileNode.department_id.is_(None)
        )
    if parent_id is None:
        query = query.filter(FileNode.parent_id.is_(None))
    else:
        query = query.filter(FileNode.parent_id == parent_id)
    return query.first() is not None


def restore(user: User, trash_id: int) -> FileNode:
    item = db.session.get(TrashItem, int(trash_id))
    if item is None:
        raise ApiError("回收站条目不存在", code=3520, http_status=404)
    check_trash_access(user, item)

    node = db.session.get(FileNode, item.node_id)
    if node is None:
        db.session.delete(item)
        db.session.commit()
        raise ApiError("原文件已不存在，无法还原", code=3521, http_status=410)

    # 原父仍在且为正常文件夹则还原回原处，否则回到根
    target_parent_id = item.original_parent_id
    if target_parent_id is not None:
        parent = db.session.get(FileNode, target_parent_id)
        if parent is None or parent.status != "normal" or not parent.is_folder:
            target_parent_id = None

    final_name = _unique_restore_name(
        item.owner_user_id, target_parent_id, item.department_id,
        item.original_name, exclude_id=node.id,
    )

    ids = collect_subtree_ids(node.id)
    db.session.query(FileNode).filter(FileNode.id.in_(ids)).update(
        {
            FileNode.status: "normal",
            FileNode.deleted_time: None,
            FileNode.delete_operator_id: None,
        },
        synchronize_session=False,
    )
    node.parent_id = target_parent_id
    node.file_name = final_name
    db.session.delete(item)
    db.session.commit()

    if node.department_id:
        from .file_service import _log_dept_file_op

        _log_dept_file_op(user, "file_restore", node, {"from_trash": item.id})
    return node


# ---------------------------------------------------------------------------
# 定时清理
# ---------------------------------------------------------------------------

def purge_expired(now: datetime | None = None) -> dict:
    """彻底删除已过保留期的回收站条目。返回清理数量与释放字节数。"""
    now = now or _utcnow()
    items = (
        db.session.query(TrashItem)
        .filter(TrashItem.expire_time <= now)
        .order_by(TrashItem.expire_time)
        .all()
    )
    count = 0
    freed = 0
    for item in items:
        node = db.session.get(FileNode, item.node_id)
        if node is None:
            db.session.delete(item)
            db.session.commit()
            count += 1
            continue
        freed += hard_delete(node, item.operator_id)
        count += 1
    return {"count": count, "freed": freed}
