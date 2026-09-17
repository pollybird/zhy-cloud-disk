"""文件/文件夹业务逻辑：目录树、分类、配额、递归删除。

1.1.0 扩展：支持部门文件（department_id 不为空时，权限由 permission_service 检查）。
个人文件（department_id 为空）逻辑完全不变（1.0.0 兼容）。
"""
from datetime import datetime, timezone

from flask import current_app
from sqlalchemy import and_, func, or_, update
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models.department import Department
from ..models.file_node import FileNode
from ..models.user import User
from ..utils.errors import ApiError
from . import log_service
from . import storage_service

NAME_MAX = 255


# ---------------------------------------------------------------------------
# 归属与权限
# ---------------------------------------------------------------------------

def get_owned_node(
    user: User, node_id: int, folders_only: bool = False, required: str = "read"
) -> FileNode:
    """获取用户有权访问的文件节点。

    个人文件：仅 owner 可访问（required 参数忽略）。
    部门文件：通过 permission_service.check_file_access 检查权限。
    """
    node = db.session.get(FileNode, int(node_id))
    if node is None or node.status != "normal":
        raise ApiError("文件不存在", code=3101, http_status=404)
    if folders_only and not node.is_folder:
        raise ApiError("目标不是文件夹", code=3102)

    if node.department_id is not None:
        # 部门文件：权限检查
        from . import permission_service

        if not permission_service.check_file_access(user, node, required):
            raise ApiError("无权访问该文件", code=4032, http_status=403)
    elif node.user_id != user.id:
        # 个人文件：仅 owner
        raise ApiError("文件不存在", code=3101, http_status=404)

    return node


def _check_sibling_name(
    user_id: int, parent_id: int | None, name: str,
    exclude_id: int | None = None, department_id: int | None = None,
) -> None:
    query = db.session.query(FileNode).filter(
        FileNode.file_name == name,
        FileNode.status == "normal",
    )
    if department_id:
        query = query.filter(FileNode.department_id == department_id)
    else:
        query = query.filter(
            FileNode.user_id == user_id,
            FileNode.department_id.is_(None),
        )
    query = query.filter(
        FileNode.parent_id.is_(None) if parent_id is None else FileNode.parent_id == parent_id
    )
    if exclude_id is not None:
        query = query.filter(FileNode.id != exclude_id)
    if query.first() is not None:
        raise ApiError("同级目录下已存在同名文件或文件夹", code=3103, http_status=409)


def validate_node_name(name: str) -> str:
    name = storage_service.safe_original_name(name)
    if len(name) > NAME_MAX:
        raise ApiError("文件名过长", code=3104)
    if name in {".", ".."}:
        raise ApiError("文件名不合法", code=3104)
    return name


def _denied_suffix(suffix: str) -> bool:
    return suffix.lower() in current_app.config["DENIED_EXTENSIONS"]


# ---------------------------------------------------------------------------
# 列表与面包屑
# ---------------------------------------------------------------------------

def list_files(
    user: User,
    parent_id: int | None = None,
    department_id: int | None = None,
    category: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 50,
) -> dict:
    if department_id:
        from . import permission_service

        if not permission_service.check_department_access(user, department_id, "read"):
            raise ApiError("无权访问该部门文件", code=4032, http_status=403)
        query = db.session.query(FileNode).filter(
            FileNode.department_id == department_id, FileNode.status == "normal"
        )
    else:
        query = db.session.query(FileNode).filter(
            FileNode.user_id == user.id,
            FileNode.department_id.is_(None),
            FileNode.status == "normal",
        )

    if category and category in current_app.config["CATEGORY_EXTENSIONS"]:
        exts = current_app.config["CATEGORY_EXTENSIONS"][category]
        query = query.filter(
            FileNode.is_folder.is_(False), FileNode.file_suffix.in_(exts)
        )
        if keyword:
            query = query.filter(
                FileNode.file_name.like(_like_pattern(keyword), escape="\\")
            )
    elif keyword:
        query = query.filter(
            FileNode.file_name.like(_like_pattern(keyword), escape="\\")
        )
    else:
        if parent_id:
            get_owned_node(user, parent_id, folders_only=True)
            query = query.filter(FileNode.parent_id == parent_id)
        else:
            query = query.filter(FileNode.parent_id.is_(None))

    total = query.count()
    rows = (
        query.order_by(FileNode.is_folder.desc(), FileNode.upload_time.desc())
        .offset(max(page - 1, 0) * size)
        .limit(size)
        .all()
    )
    items = [r.to_dict() for r in rows]
    result = {
        "total": total,
        "page": page,
        "size": size,
        "parent_id": parent_id,
        "breadcrumb": breadcrumb(user, parent_id) if parent_id and not category and not keyword else [],
        "items": items,
    }
    if department_id:
        # 部门文件：标注当前目录与每个节点的有效权限，供前端按钮显隐
        from . import permission_service

        if parent_id:
            container = db.session.get(FileNode, parent_id)
            container_perm = (
                permission_service.effective_node_permission(user, container)
                if container is not None
                else "none"
            )
        else:
            container_perm = permission_service.effective_department_permission(
                user, department_id
            )
        # 文件夹以自身有效权限为准，文件继承所在目录（即当前容器）权限
        for data, node in zip(items, rows):
            data["access"] = (
                permission_service.effective_node_permission(user, node)
                if node.is_folder
                else container_perm
            )
        result["access"] = container_perm
    return result


def _like_pattern(keyword: str) -> str:
    """转义 LIKE 通配符，避免 % _ 被当作模式字符。"""
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def breadcrumb(user: User, folder_id: int | None) -> list[dict]:
    if not folder_id:
        return []
    path = []
    seen = set()
    current = db.session.get(FileNode, int(folder_id))
    while current is not None and current.id not in seen:
        if current.status != "normal":
            raise ApiError("文件夹不存在", code=3101, http_status=404)
        # 权限校验：个人文件检查 owner，部门文件由 get_owned_node 检查
        if current.department_id is not None:
            get_owned_node(user, current.id, required="read")
        elif current.user_id != user.id:
            raise ApiError("文件夹不存在", code=3101, http_status=404)
        path.append({"id": current.id, "file_name": current.file_name})
        seen.add(current.id)
        current = db.session.get(FileNode, current.parent_id) if current.parent_id else None
    path.reverse()
    return path


def list_child_folders(
    user: User, parent_id: int | None, department_id: int | None = None
) -> list[dict]:
    """懒加载移动目录树的单层子文件夹。

    个人空间（department_id 为空）：仅 owner 文件夹。
    部门网盘：仅返回用户具备写入权限的文件夹（移动目标必须可写）。
    """
    if department_id:
        from . import permission_service

        query = db.session.query(FileNode).filter(
            FileNode.department_id == department_id,
            FileNode.status == "normal",
            FileNode.is_folder.is_(True),
        )
        if parent_id:
            # 进入子文件夹需对该文件夹有写权限
            get_owned_node(user, parent_id, folders_only=True, required="write")
            query = query.filter(FileNode.parent_id == parent_id)
        else:
            # 移动到部门根目录需部门级写权限
            if not permission_service.check_department_access(
                user, department_id, "write"
            ):
                raise ApiError("无权在该部门移动文件", code=4032, http_status=403)
            query = query.filter(FileNode.parent_id.is_(None))
        rows = query.order_by(FileNode.file_name.asc()).all()
        # 仅列出可作为移动目标（可写）的子文件夹
        result = []
        for r in rows:
            if permission_service.effective_node_permission(user, r) == "read_write":
                result.append(r.to_dict())
        return result

    query = db.session.query(FileNode).filter(
        FileNode.user_id == user.id,
        FileNode.status == "normal",
        FileNode.is_folder.is_(True),
    )
    if parent_id:
        get_owned_node(user, parent_id, folders_only=True)
        query = query.filter(FileNode.parent_id == parent_id)
    else:
        query = query.filter(FileNode.parent_id.is_(None))
    rows = query.order_by(FileNode.file_name.asc()).all()
    return [r.to_dict() for r in rows]


# ---------------------------------------------------------------------------
# 上传 / 建文件夹 / 重命名 / 移动 / 删除
# ---------------------------------------------------------------------------

def check_duplicate(
    user: User,
    parent_id: int | None,
    file_name: str,
    file_hash: str | None,
    department_id: int | None = None,
) -> dict:
    """预检同名文件冲突。

    返回 {action: upload|skip|conflict, existing: dict|None, hash_missing: bool, is_folder: bool}
    """
    name = storage_service.safe_original_name(file_name)
    if department_id:
        from . import permission_service

        if not permission_service.check_department_access(user, department_id, "write"):
            raise ApiError("无权上传到该部门", code=4032, http_status=403)
        query = db.session.query(FileNode).filter(
            FileNode.department_id == department_id,
            FileNode.parent_id.is_(None) if parent_id is None else FileNode.parent_id == parent_id,
            FileNode.file_name == name,
            FileNode.status == "normal",
        )
    else:
        query = db.session.query(FileNode).filter(
            FileNode.user_id == user.id,
            FileNode.department_id.is_(None),
            FileNode.parent_id.is_(None) if parent_id is None else FileNode.parent_id == parent_id,
            FileNode.file_name == name,
            FileNode.status == "normal",
        )
    node = query.first()
    if node is None:
        return {"action": "upload", "existing": None, "hash_missing": False, "is_folder": False}

    if node.is_folder:
        return {"action": "conflict", "existing": node.to_dict(), "hash_missing": False, "is_folder": True}

    if file_hash and node.file_hash and node.file_hash == file_hash:
        return {"action": "skip", "existing": node.to_dict(), "hash_missing": False, "is_folder": False}

    return {
        "action": "conflict",
        "existing": node.to_dict(),
        "hash_missing": node.file_hash is None,
        "is_folder": False,
    }


def upload_file(
    user: User,
    file_storage,
    parent_id: int | None = None,
    file_hash: str | None = None,
    mode: str = "normal",
    overwrite_id: int | None = None,
    department_id: int | None = None,
) -> FileNode:
    if parent_id:
        get_owned_node(user, parent_id, folders_only=True, required="write")

    if department_id:
        from . import permission_service

        if not permission_service.check_department_access(user, department_id, "write"):
            raise ApiError("无权上传到该部门", code=4032, http_status=403)

    original_name = storage_service.safe_original_name(file_storage.filename)
    suffix = storage_service.extract_suffix(original_name)
    if _denied_suffix(suffix):
        raise ApiError(f"禁止上传 .{suffix} 类型的文件", code=3105)

    if mode == "overwrite" and overwrite_id:
        existing = get_owned_node(user, overwrite_id, required="write")
        if existing.is_folder:
            raise ApiError("不能覆盖文件夹", code=3108)
        return _do_overwrite(user, file_storage, existing, file_hash, department_id)

    save_path, suffix, file_size, server_hash = storage_service.save_stream_hashed(
        file_storage, user.id, department_id
    )
    if file_hash and file_hash != server_hash:
        storage_service.remove_physical(save_path)
        raise ApiError("文件指纹校验失败，上传可能损坏", code=3205)

    # 配额扣减：部门文件扣部门配额，个人文件扣用户配额
    try:
        if department_id:
            updated = db.session.execute(
                update(Department)
                .where(
                    and_(
                        Department.id == department_id,
                        or_(
                            Department.storage_quota <= 0,
                            Department.used_storage + file_size <= Department.storage_quota,
                        ),
                    )
                )
                .values(used_storage=Department.used_storage + file_size)
            )
        else:
            updated = db.session.execute(
                update(User)
                .where(
                    and_(
                        User.id == user.id,
                        User.used_storage + file_size <= User.total_storage,
                    )
                )
                .values(used_storage=User.used_storage + file_size)
            )
        if updated.rowcount == 0:
            storage_service.remove_physical(save_path)
            raise ApiError("存储空间不足，上传被拒绝", code=3106, http_status=413)

        node = FileNode(
            user_id=user.id,
            department_id=department_id or None,
            file_name=_unique_display_name(user.id, parent_id, original_name, department_id),
            file_suffix=suffix,
            file_size=file_size,
            save_path=save_path,
            file_hash=server_hash,
            is_folder=False,
            parent_id=parent_id or None,
            status="normal",
        )
        db.session.add(node)
        db.session.commit()
        db.session.refresh(user)
        if department_id:
            _log_dept_file_op(user, "file_upload", node)
        return node
    except IntegrityError:
        db.session.rollback()
        try:
            if department_id:
                updated = db.session.execute(
                    update(Department)
                    .where(
                        and_(
                            Department.id == department_id,
                            or_(
                                Department.storage_quota <= 0,
                                Department.used_storage + file_size <= Department.storage_quota,
                            ),
                        )
                    )
                    .values(used_storage=Department.used_storage + file_size)
                )
            else:
                updated = db.session.execute(
                    update(User)
                    .where(
                        and_(
                            User.id == user.id,
                            User.used_storage + file_size <= User.total_storage,
                        )
                    )
                    .values(used_storage=User.used_storage + file_size)
                )
            if updated.rowcount == 0:
                storage_service.remove_physical(save_path)
                raise ApiError("存储空间不足，上传被拒绝", code=3106, http_status=413)
            node.file_name = _unique_display_name(user.id, parent_id, original_name, department_id)
            db.session.add(node)
            db.session.commit()
            db.session.refresh(user)
            if department_id:
                _log_dept_file_op(user, "file_upload", node)
            return node
        except ApiError:
            raise
        except Exception:
            db.session.rollback()
            storage_service.remove_physical(save_path)
            raise
    except ApiError:
        raise
    except Exception:
        db.session.rollback()
        storage_service.remove_physical(save_path)
        raise


def _do_overwrite(
    user: User, file_storage, existing: FileNode, client_hash: str | None,
    department_id: int | None = None,
) -> FileNode:
    """覆盖原文件：UPDATE 原行，保留 id/file_name/parent_id。"""
    save_path, suffix, file_size, server_hash = storage_service.save_stream_hashed(
        file_storage, user.id, department_id or existing.department_id
    )
    if client_hash and client_hash != server_hash:
        storage_service.remove_physical(save_path)
        raise ApiError("文件指纹校验失败，上传可能损坏", code=3205)

    old_save_path = existing.save_path
    old_size = existing.file_size
    dept_id = department_id or existing.department_id
    try:
        if dept_id:
            updated = db.session.execute(
                update(Department)
                .where(
                    and_(
                        Department.id == dept_id,
                        or_(
                            Department.storage_quota <= 0,
                            Department.used_storage - old_size + file_size <= Department.storage_quota,
                        ),
                    )
                )
                .values(used_storage=Department.used_storage - old_size + file_size)
            )
        else:
            updated = db.session.execute(
                update(User)
                .where(
                    and_(
                        User.id == user.id,
                        User.used_storage - old_size + file_size <= User.total_storage,
                    )
                )
                .values(used_storage=User.used_storage - old_size + file_size)
            )
        if updated.rowcount == 0:
            storage_service.remove_physical(save_path)
            raise ApiError("存储空间不足，上传被拒绝", code=3106, http_status=413)

        existing.save_path = save_path
        existing.file_suffix = suffix
        existing.file_size = file_size
        existing.file_hash = server_hash
        existing.upload_time = datetime.now(timezone.utc)
        db.session.commit()
        db.session.refresh(user)

        if old_save_path:
            storage_service.remove_physical(old_save_path)
        if dept_id:
            _log_dept_file_op(user, "file_overwrite", existing, {"old_size": old_size, "size": file_size})
        return existing
    except ApiError:
        raise
    except Exception:
        db.session.rollback()
        storage_service.remove_physical(save_path)
        raise


def _unique_display_name(
    user_id: int, parent_id: int | None, name: str,
    department_id: int | None = None,
) -> str:
    """同名文件自动追加 (1)(2) 后缀，避免覆盖（唯一约束兜底）。"""
    base, dot, ext = name.rpartition(".")
    if not dot:
        stem, suffix_part = name, ""
    else:
        stem, suffix_part = base, f".{ext}"

    candidate = name
    index = 1
    query = db.session.query(FileNode.id).filter(
        FileNode.file_name == candidate,
        FileNode.status == "normal",
    )
    if department_id:
        query = query.filter(FileNode.department_id == department_id)
    else:
        query = query.filter(
            FileNode.user_id == user_id,
            FileNode.department_id.is_(None),
        )
    query = query.filter(
        FileNode.parent_id.is_(None) if parent_id is None else FileNode.parent_id == parent_id
    )
    while query.first():
        candidate = f"{stem} ({index}){suffix_part}"
        index += 1
        if index > 9999:
            raise ApiError("同名文件过多", code=3107)
        # 重新构建查询（file_name 变了）
        query = db.session.query(FileNode.id).filter(
            FileNode.file_name == candidate,
            FileNode.status == "normal",
        )
        if department_id:
            query = query.filter(FileNode.department_id == department_id)
        else:
            query = query.filter(
                FileNode.user_id == user_id,
                FileNode.department_id.is_(None),
            )
        query = query.filter(
            FileNode.parent_id.is_(None) if parent_id is None else FileNode.parent_id == parent_id
        )
    return candidate[:NAME_MAX]


def create_folder(
    user: User, parent_id: int | None, name: str,
    department_id: int | None = None,
) -> FileNode:
    name = validate_node_name(name)
    if parent_id:
        get_owned_node(user, parent_id, folders_only=True, required="write")
    if department_id:
        from . import permission_service

        if not permission_service.check_department_access(user, department_id, "write"):
            raise ApiError("无权在该部门创建文件夹", code=4032, http_status=403)
    _check_sibling_name(user.id, parent_id or None, name, department_id=department_id)
    folder = FileNode(
        user_id=user.id,
        department_id=department_id or None,
        file_name=name,
        file_suffix="",
        file_size=0,
        save_path=None,
        is_folder=True,
        parent_id=parent_id or None,
        status="normal",
    )
    db.session.add(folder)
    db.session.commit()
    if department_id:
        _log_dept_file_op(user, "folder_create", folder)
    return folder


def rename_node(user: User, node_id: int, new_name: str) -> FileNode:
    node = get_owned_node(user, node_id, required="write")
    new_name = validate_node_name(new_name)
    if not node.is_folder:
        suffix = storage_service.extract_suffix(new_name)
        if _denied_suffix(suffix):
            raise ApiError(f"不允许使用 .{suffix} 后缀", code=3105)
        node.file_suffix = suffix
    _check_sibling_name(
        user.id, node.parent_id, new_name,
        exclude_id=node.id, department_id=node.department_id,
    )
    old_name = node.file_name
    node.file_name = new_name
    db.session.commit()
    if node.department_id:
        _log_dept_file_op(user, "file_rename", node, {"old_name": old_name})
    return node


def move_node(user: User, node_id: int, target_parent_id: int | None) -> FileNode:
    node = get_owned_node(user, node_id, required="write")
    target_id = target_parent_id or None

    if target_id is not None:
        target = get_owned_node(user, target_id, folders_only=True, required="write")
        # 禁止个人空间与部门网盘之间跨域移动（物理存储与配额归属不同）
        if (node.department_id or None) != (target.department_id or None):
            raise ApiError(
                "不能在个人空间与部门网盘之间移动文件", code=3109, http_status=409
            )
        # 防止移动到自身或自己的子孙目录
        ancestor_ids = _subtree_folder_ids(user, node.id, node.department_id)
        ancestor_ids.add(node.id)
        if target.id in ancestor_ids:
            raise ApiError("不能移动到自身或其子文件夹内", code=3108)

    if target_id != node.parent_id:
        _check_sibling_name(
            user.id, target_id, node.file_name,
            exclude_id=node.id, department_id=node.department_id,
        )
        old_parent_id = node.parent_id
        node.parent_id = target_id
        db.session.commit()
        if node.department_id:
            _log_dept_file_op(user, "file_move", node, {"old_parent_id": old_parent_id, "new_parent_id": target_id})
    return node


def delete_node(user: User, node_id: int) -> None:
    node = get_owned_node(user, node_id, required="delete")

    ids = _subtree_ids(node)
    file_nodes = (
        db.session.query(FileNode)
        .filter(FileNode.id.in_(ids), FileNode.is_folder.is_(False))
        .all()
    )
    physical_paths = [f.save_path for f in file_nodes if f.save_path]
    freed_space = sum(f.file_size for f in file_nodes)

    db.session.query(FileNode).filter(FileNode.id.in_(ids)).update(
        {FileNode.status: "deleted"}, synchronize_session=False
    )
    # 释放配额：部门文件退部门配额，个人文件退用户配额
    if node.department_id:
        locked = db.session.query(Department).filter(
            Department.id == node.department_id
        ).with_for_update().first()
        if locked is not None and freed_space:
            locked.used_storage = max(locked.used_storage - freed_space, 0)
    else:
        locked_user = db.session.query(User).filter(
            User.id == user.id
        ).with_for_update().first()
        if locked_user is not None and freed_space:
            locked_user.used_storage = max(locked_user.used_storage - freed_space, 0)
    db.session.commit()

    for path in physical_paths:
        storage_service.remove_physical(path)
    db.session.refresh(user)

    if node.department_id:
        _log_dept_file_op(
            user, "file_delete", node,
            {"freed": freed_space, "deleted_count": len(ids)},
        )


def _log_dept_file_op(
    user: User, action: str, node: FileNode, detail: dict | None = None
) -> None:
    """记录部门文件操作日志（个人文件不记录，保持 1.0.0 行为不变）。"""
    log_service.record(
        user.id, action,
        "folder" if node.is_folder else "file",
        node.id, node.department_id,
        {"name": node.file_name, **(detail or {})},
    )


def _subtree_ids(root: FileNode) -> set[int]:
    """返回含根在内的全部子孙节点 ID（逐层查询，兼容 SQLite/MySQL）。"""
    ids = {root.id}
    frontier = [root.id]
    while frontier:
        children = [
            row[0]
            for row in db.session.query(FileNode.id)
            .filter(
                FileNode.parent_id.in_(frontier),
                FileNode.status == "normal",
            )
            .all()
        ]
        if not children:
            break
        ids.update(children)
        frontier = children
    return ids


def _subtree_folder_ids(user: User, folder_id: int, department_id: int | None = None) -> set[int]:
    """收集文件夹子孙 ID（移动环检测用）。"""
    ids = set()
    frontier = [folder_id]
    while frontier:
        query = db.session.query(FileNode.id).filter(
            FileNode.parent_id.in_(frontier),
            FileNode.is_folder.is_(True),
            FileNode.status == "normal",
        )
        if department_id:
            query = query.filter(FileNode.department_id == department_id)
        else:
            query = query.filter(
                FileNode.user_id == user.id,
                FileNode.department_id.is_(None),
            )
        children = [row[0] for row in query.all()]
        if not children:
            break
        ids.update(children)
        frontier = children
    return ids
