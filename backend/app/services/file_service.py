"""文件/文件夹业务逻辑：目录树、分类、配额、递归删除。"""
from datetime import datetime, timezone

from flask import current_app
from sqlalchemy import and_, func, or_, update
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models.file_node import FileNode
from ..models.user import User
from ..utils.errors import ApiError
from . import storage_service

NAME_MAX = 255


# ---------------------------------------------------------------------------
# 归属与基础查询
# ---------------------------------------------------------------------------

def get_owned_node(user: User, node_id: int, folders_only: bool = False) -> FileNode:
    node = db.session.get(FileNode, int(node_id))
    if node is None or node.user_id != user.id or node.status != "normal":
        raise ApiError("文件不存在", code=3101, http_status=404)
    if folders_only and not node.is_folder:
        raise ApiError("目标不是文件夹", code=3102)
    return node


def _check_sibling_name(
    user_id: int, parent_id: int | None, name: str, exclude_id: int | None = None
) -> None:
    query = db.session.query(FileNode).filter(
        FileNode.user_id == user_id,
        FileNode.parent_id.is_(None) if parent_id is None else FileNode.parent_id == parent_id,
        FileNode.file_name == name,
        FileNode.status == "normal",
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
    category: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 50,
) -> dict:
    query = db.session.query(FileNode).filter(
        FileNode.user_id == user.id, FileNode.status == "normal"
    )

    if category and category in current_app.config["CATEGORY_EXTENSIONS"]:
        # 分类模式：平铺展示该类型文件
        exts = current_app.config["CATEGORY_EXTENSIONS"][category]
        query = query.filter(
            FileNode.is_folder.is_(False), FileNode.file_suffix.in_(exts)
        )
        if keyword:
            query = query.filter(
                FileNode.file_name.like(_like_pattern(keyword), escape="\\")
            )
    elif keyword:
        # 关键词模式：在用户全部文件中全局搜索（含子目录）
        query = query.filter(
            FileNode.file_name.like(_like_pattern(keyword), escape="\\")
        )
    else:
        # 目录模式：列出当前层级
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
    return {
        "total": total,
        "page": page,
        "size": size,
        "parent_id": parent_id,
        "breadcrumb": breadcrumb(user, parent_id) if parent_id and not category and not keyword else [],
        "items": [r.to_dict() for r in rows],
    }


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
        if current.user_id != user.id or current.status != "normal":
            raise ApiError("文件夹不存在", code=3101, http_status=404)
        path.append({"id": current.id, "file_name": current.file_name})
        seen.add(current.id)
        current = db.session.get(FileNode, current.parent_id) if current.parent_id else None
    path.reverse()
    return path


def list_child_folders(user: User, parent_id: int | None) -> list[dict]:
    """懒加载移动目录树的单层子文件夹。"""
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
) -> dict:
    """预检同名文件冲突。

    返回 {action: upload|skip|conflict, existing: dict|None, hash_missing: bool, is_folder: bool}
    """
    name = storage_service.safe_original_name(file_name)
    node = (
        db.session.query(FileNode)
        .filter(
            FileNode.user_id == user.id,
            FileNode.parent_id.is_(None) if parent_id is None else FileNode.parent_id == parent_id,
            FileNode.file_name == name,
            FileNode.status == "normal",
        )
        .first()
    )
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
) -> FileNode:
    if parent_id:
        get_owned_node(user, parent_id, folders_only=True)

    original_name = storage_service.safe_original_name(file_storage.filename)
    suffix = storage_service.extract_suffix(original_name)
    if _denied_suffix(suffix):
        raise ApiError(f"禁止上传 .{suffix} 类型的文件", code=3105)

    if mode == "overwrite" and overwrite_id:
        existing = get_owned_node(user, overwrite_id)
        if existing.is_folder:
            raise ApiError("不能覆盖文件夹", code=3108)
        return _do_overwrite(user, file_storage, existing, file_hash)

    # 落盘并计算服务端哈希
    save_path, suffix, file_size, server_hash = storage_service.save_stream_hashed(
        file_storage, user.id
    )
    # 客户端哈希校验（防伪造/传输损坏）
    if file_hash and file_hash != server_hash:
        storage_service.remove_physical(save_path)
        raise ApiError("文件指纹校验失败，上传可能损坏", code=3205)

    try:
        # 原子配额扣减：超额时 UPDATE 影响 0 行
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
            file_name=_unique_display_name(user.id, parent_id, original_name),
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
        return node
    except IntegrityError:
        # 并发同名校验：唯一约束兜底，改名重试（配额已随 rollback 回滚，需重扣）
        db.session.rollback()
        try:
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
            node.file_name = _unique_display_name(user.id, parent_id, original_name)
            db.session.add(node)
            db.session.commit()
            db.session.refresh(user)
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
    user: User, file_storage, existing: FileNode, client_hash: str | None
) -> FileNode:
    """覆盖原文件：UPDATE 原行，保留 id/file_name/parent_id。"""
    save_path, suffix, file_size, server_hash = storage_service.save_stream_hashed(
        file_storage, user.id
    )
    if client_hash and client_hash != server_hash:
        storage_service.remove_physical(save_path)
        raise ApiError("文件指纹校验失败，上传可能损坏", code=3205)

    old_save_path = existing.save_path
    old_size = existing.file_size
    try:
        # 原子配额：退旧扣新一次 UPDATE
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

        # 提交成功后删旧物理文件
        if old_save_path:
            storage_service.remove_physical(old_save_path)
        return existing
    except ApiError:
        raise
    except Exception:
        db.session.rollback()
        storage_service.remove_physical(save_path)
        raise


def _unique_display_name(
    user_id: int, parent_id: int | None, name: str
) -> str:
    """同名文件自动追加 (1)(2) 后缀，避免覆盖（唯一约束兜底）。"""
    base, dot, ext = name.rpartition(".")
    if not dot:
        stem, suffix_part = name, ""
    else:
        stem, suffix_part = base, f".{ext}"

    candidate = name
    index = 1
    while db.session.query(FileNode.id).filter(
        FileNode.user_id == user_id,
        FileNode.parent_id.is_(None) if parent_id is None else FileNode.parent_id == parent_id,
        FileNode.file_name == candidate,
        FileNode.status == "normal",
    ).first():
        candidate = f"{stem} ({index}){suffix_part}"
        index += 1
        if index > 9999:
            raise ApiError("同名文件过多", code=3107)
    return candidate[:NAME_MAX]


def create_folder(user: User, parent_id: int | None, name: str) -> FileNode:
    name = validate_node_name(name)
    if parent_id:
        get_owned_node(user, parent_id, folders_only=True)
    _check_sibling_name(user.id, parent_id or None, name)
    folder = FileNode(
        user_id=user.id,
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
    return folder


def rename_node(user: User, node_id: int, new_name: str) -> FileNode:
    node = get_owned_node(user, node_id)
    new_name = validate_node_name(new_name)
    if not node.is_folder:
        suffix = storage_service.extract_suffix(new_name)
        if _denied_suffix(suffix):
            raise ApiError(f"不允许使用 .{suffix} 后缀", code=3105)
        node.file_suffix = suffix
    _check_sibling_name(user.id, node.parent_id, new_name, exclude_id=node.id)
    node.file_name = new_name
    db.session.commit()
    return node


def move_node(user: User, node_id: int, target_parent_id: int | None) -> FileNode:
    node = get_owned_node(user, node_id)
    target_id = target_parent_id or None

    if target_id is not None:
        target = get_owned_node(user, target_id, folders_only=True)
        # 防止移动到自身或自己的子孙目录
        ancestor_ids = _subtree_folder_ids(user, node.id)
        ancestor_ids.add(node.id)
        if target.id in ancestor_ids:
            raise ApiError("不能移动到自身或其子文件夹内", code=3108)

    if target_id != node.parent_id:
        _check_sibling_name(user.id, target_id, node.file_name, exclude_id=node.id)
        node.parent_id = target_id
        db.session.commit()
    return node


def delete_node(user: User, node_id: int) -> None:
    node = get_owned_node(user, node_id)

    # 收集子孙节点
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
    # 释放配额（读取-改值-写回，下限保护 0；单用户删除并发极低）
    locked_user = db.session.query(User).filter(User.id == user.id).with_for_update().first()
    if locked_user is not None and freed_space:
        locked_user.used_storage = max(locked_user.used_storage - freed_space, 0)
    db.session.commit()

    # 事务提交后清理磁盘文件
    for path in physical_paths:
        storage_service.remove_physical(path)
    db.session.refresh(user)


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


def _subtree_folder_ids(user: User, folder_id: int) -> set[int]:
    """收集文件夹子孙 ID（移动环检测用）。"""
    ids = set()
    frontier = [folder_id]
    while frontier:
        children = [
            row[0]
            for row in db.session.query(FileNode.id)
            .filter(
                FileNode.user_id == user.id,
                FileNode.parent_id.in_(frontier),
                FileNode.is_folder.is_(True),
                FileNode.status == "normal",
            )
            .all()
        ]
        if not children:
            break
        ids.update(children)
        frontier = children
    return ids
