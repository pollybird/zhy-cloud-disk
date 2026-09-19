"""文件/文件夹业务逻辑：目录树、分类、配额、递归删除。

1.1.0 扩展：支持部门文件（department_id 不为空时，权限由 permission_service 检查）。
个人文件（department_id 为空）逻辑完全不变（1.0.0 兼容）。
"""
from datetime import datetime, timedelta, timezone
import uuid

from flask import current_app
from sqlalchemy import and_, func, or_, update
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models.department import Department
from ..models.file_node import FileNode
from ..models.upload_session import UploadChunk, UploadSession
from ..models.user import User
from ..utils.errors import ApiError
from . import blob_service
from . import log_service
from . import permission_service
from . import setting_service
from . import storage_service
from . import trash_service
from . import version_service

NAME_MAX = 255

# 分片上传参数
CHUNK_SIZE_DEFAULT = 5 * 1024 * 1024
CHUNK_SIZE_MIN = 1024 * 1024
CHUNK_SIZE_MAX = 25 * 1024 * 1024
SESSION_TTL = timedelta(hours=24)


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
        # 写/删操作：文件正被他人排他锁定时拒绝（持有者本人放行）
        if required in ("write", "delete"):
            from . import file_lock_service

            file_lock_service.ensure_unlocked(user, node)
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
        from . import file_lock_service

        locks = file_lock_service.lock_map([r.id for r in rows if not r.is_folder])
        for data, node in zip(items, rows):
            data["access"] = (
                permission_service.effective_node_permission(user, node)
                if node.is_folder
                else container_perm
            )
            # 排他编辑锁标注（仅文件）：locked / locked_by_me / lock_user_name
            lock = locks.get(node.id)
            data["locked"] = lock is not None
            data["locked_by_me"] = bool(lock and lock.user_id == user.id)
            data["lock_user_name"] = lock.user_name if lock else None
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

    staged_path, file_size, server_hash = storage_service.save_staged_stream(file_storage)
    if file_hash and file_hash != server_hash:
        storage_service.remove_staging(staged_path)
        raise ApiError("文件指纹校验失败，上传可能损坏", code=3205)

    return _commit_new_file(
        user, parent_id, department_id, original_name, suffix,
        file_size, server_hash, staged_path, action="file_upload",
    )


def _charge_quota(user_id: int, department_id: int | None, size: int) -> bool:
    """原子扣减逻辑配额。部门 0=不限；个人无 0 语义。成功返回 True。"""
    if department_id:
        updated = db.session.execute(
            update(Department)
            .where(
                and_(
                    Department.id == department_id,
                    or_(
                        Department.storage_quota <= 0,
                        Department.used_storage + size <= Department.storage_quota,
                    ),
                )
            )
            .values(used_storage=Department.used_storage + size)
        )
    else:
        updated = db.session.execute(
            update(User)
            .where(
                and_(
                    User.id == user_id,
                    User.used_storage + size <= User.total_storage,
                )
            )
            .values(used_storage=User.used_storage + size)
        )
    return updated.rowcount > 0


def _register_blob_and_node(
    user: User, parent_id: int | None, department_id: int | None,
    original_name: str, suffix: str, file_size: int,
    server_hash: str, staged_path: str | None,
) -> FileNode:
    """当前事务内：注册/复用 blob（retain）并构造未提交的 FileNode。

    staged_path 为 None 表示物理块已在 blob 目录（秒传/事务重试场景）。
    """
    if staged_path is not None:
        blob = blob_service.get_or_create(server_hash, file_size, staged_path)
    else:
        blob = blob_service.find_usable(server_hash, file_size)
        if blob is None:
            raise ApiError("文件物理块缺失，请重新上传", code=3211)
    blob_service.retain(blob)
    return FileNode(
        user_id=user.id,
        department_id=department_id or None,
        file_name=_unique_display_name(user.id, parent_id, original_name, department_id),
        file_suffix=suffix,
        file_size=file_size,
        save_path=blob.save_path,
        file_hash=server_hash,
        is_folder=False,
        parent_id=parent_id or None,
        status="normal",
    )


def _commit_new_file(
    user: User, parent_id: int | None, department_id: int | None,
    original_name: str, suffix: str, file_size: int,
    server_hash: str, staged_path: str | None, action: str = "file_upload",
) -> FileNode:
    """扣配额 → blob 注册 → 建节点提交；唯一约束冲突整体重试一次。

    物理块在首次注册时已原子移入 blob 目录，事务回滚不移动文件，
    重试时 staged_path 置 None 直接复用已落位的物理块。
    """
    try:
        if not _charge_quota(user.id, department_id, file_size):
            if staged_path is not None:
                storage_service.remove_staging(staged_path)
            raise ApiError("存储空间不足，上传被拒绝", code=3106, http_status=413)
        node = _register_blob_and_node(
            user, parent_id, department_id, original_name, suffix,
            file_size, server_hash, staged_path,
        )
        db.session.add(node)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if not _charge_quota(user.id, department_id, file_size):
            raise ApiError("存储空间不足，上传被拒绝", code=3106, http_status=413)
        node = _register_blob_and_node(
            user, parent_id, department_id, original_name, suffix,
            file_size, server_hash, None,
        )
        db.session.add(node)
        db.session.commit()
    except ApiError:
        db.session.rollback()
        if staged_path is not None:
            storage_service.remove_staging(staged_path)
        raise
    except Exception:
        db.session.rollback()
        if staged_path is not None:
            storage_service.remove_staging(staged_path)
        raise

    if staged_path is not None:
        storage_service.remove_staging(staged_path)
    db.session.refresh(user)
    if department_id:
        _log_dept_file_op(user, action, node)
    return node


def _do_overwrite(
    user: User, file_storage, existing: FileNode, client_hash: str | None,
    department_id: int | None = None,
) -> FileNode:
    """覆盖原文件：UPDATE 原行，保留 id/file_name/parent_id。"""
    staged_path, file_size, server_hash = storage_service.save_staged_stream(file_storage)
    suffix = storage_service.extract_suffix(
        storage_service.safe_original_name(file_storage.filename)
    )
    if client_hash and client_hash != server_hash:
        storage_service.remove_staging(staged_path)
        raise ApiError("文件指纹校验失败，上传可能损坏", code=3205)

    old_save_path = existing.save_path
    old_hash = existing.file_hash
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
            storage_service.remove_staging(staged_path)
            raise ApiError("存储空间不足，上传被拒绝", code=3106, http_status=413)

        blob = blob_service.get_or_create(server_hash, file_size, staged_path)
        blob_service.retain(blob)

        # 旧内容处理：版本开关开启且内容变化 → 归档为历史版本（引用转移，
        # 计数不变）；否则沿用 v1.2.0 逻辑立即释放旧引用。
        version_to_unlink: list[str] = []
        old_kind, old_release_path = ("alive", None)
        content_changed = bool(old_save_path) and server_hash != old_hash
        if setting_service.is_version_enabled() and content_changed:
            version_service.archive_version(existing, user.id)
            version_to_unlink = version_service.prune_versions(existing.id)
        else:
            # 新旧内容相同（同 hash）时净计数不变、物理文件保留
            old_kind, old_release_path = blob_service.release_for_hash(
                old_hash, old_save_path
            )

        existing.save_path = blob.save_path
        existing.file_suffix = suffix
        existing.file_size = file_size
        existing.file_hash = server_hash
        existing.upload_time = datetime.now(timezone.utc)
        db.session.commit()
        db.session.refresh(user)

        for path in version_to_unlink:
            storage_service.remove_physical(path)
        if old_kind == "removed" and old_release_path:
            storage_service.remove_physical(old_release_path)
        elif old_kind == "legacy" and old_save_path:
            # 1.0/1.1 旧物理文件：无 blob 管理，直接删除
            storage_service.remove_physical(old_save_path)
        if dept_id:
            _log_dept_file_op(user, "file_overwrite", existing, {"old_size": old_size, "size": file_size})
        return existing
    except ApiError:
        db.session.rollback()
        storage_service.remove_staging(staged_path)
        raise
    except Exception:
        db.session.rollback()
        storage_service.remove_staging(staged_path)
        raise


# ---------------------------------------------------------------------------
# 1.2.0 跨用户秒传
# ---------------------------------------------------------------------------

def _ensure_upload_target(user: User, parent_id: int | None, department_id: int | None) -> None:
    """上传/秒传/分片初始化共用的目标权限校验。"""
    if parent_id:
        get_owned_node(user, parent_id, folders_only=True, required="write")
    if department_id and not permission_service.check_department_access(
        user, department_id, "write"
    ):
        raise ApiError("无权上传到该部门", code=4032, http_status=403)


def _sibling_node(
    user_id: int, parent_id: int | None, department_id: int | None, name: str
) -> FileNode | None:
    query = db.session.query(FileNode).filter(
        FileNode.parent_id.is_(None) if parent_id is None else FileNode.parent_id == parent_id,
        FileNode.file_name == name,
        FileNode.status == "normal",
    )
    if department_id:
        query = query.filter(FileNode.department_id == department_id)
    else:
        query = query.filter(
            FileNode.user_id == user_id, FileNode.department_id.is_(None)
        )
    return query.first()


def instant_upload(
    user: User, parent_id: int | None, department_id: int | None,
    file_name: str, file_size: int, file_hash: str | None,
) -> dict:
    """零字节秒传：blob 命中则直接建引用，未命中返回 instant:false 由客户端回退。"""
    name = storage_service.safe_original_name(file_name)
    suffix = storage_service.extract_suffix(name)
    if _denied_suffix(suffix):
        raise ApiError(f"禁止上传 .{suffix} 类型的文件", code=3105)
    h = blob_service.normalize_hash(file_hash)
    if h is None or not isinstance(file_size, int) or file_size <= 0:
        return {"instant": False}
    if file_size > int(current_app.config["MAX_UPLOAD_SIZE"]):
        raise ApiError("文件超过最大允许大小", code=3202, http_status=413)

    _ensure_upload_target(user, parent_id, department_id)

    if blob_service.find_usable(h, file_size) is None:
        return {"instant": False}

    # 同目录同名且同 hash：直接视为已有，跳过且不重复扣配额
    sibling = _sibling_node(user.id, parent_id, department_id, name)
    if sibling is not None and not sibling.is_folder and sibling.file_hash == h:
        return {"instant": True, "skipped": True, "node": sibling.to_dict()}
    if sibling is not None and sibling.is_folder:
        raise ApiError("同名文件夹已存在", code=3107)

    node = _commit_new_file(
        user, parent_id, department_id, name, suffix,
        file_size, h, None, action="file_instant",
    )
    return {"instant": True, "skipped": False, "node": node.to_dict()}


# ---------------------------------------------------------------------------
# 1.2.0 分片上传 / 断点续传
# ---------------------------------------------------------------------------

def _get_owned_session(user: User, upload_id: str, active_only: bool = True) -> UploadSession:
    session = db.session.get(UploadSession, upload_id)
    if session is None or session.user_id != user.id:
        raise ApiError("上传会话不存在或已过期", code=3207, http_status=404)
    if active_only and (
        session.status != "uploading"
        or session.expire_time.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc)
    ):
        raise ApiError("上传会话已结束或已过期", code=3207)
    return session


def chunk_init(
    user: User, parent_id: int | None, department_id: int | None,
    file_name: str, file_size: int, file_hash: str | None,
    chunk_size: int | None,
) -> dict:
    name = storage_service.safe_original_name(file_name)
    suffix = storage_service.extract_suffix(name)
    if _denied_suffix(suffix):
        raise ApiError(f"禁止上传 .{suffix} 类型的文件", code=3105)
    h = blob_service.normalize_hash(file_hash)
    if h is None:
        raise ApiError("缺少合法的文件指纹", code=3206)
    if not isinstance(file_size, int) or file_size <= 0:
        raise ApiError("文件大小非法", code=3202)
    if file_size > int(current_app.config["MAX_UPLOAD_SIZE"]):
        raise ApiError("文件超过最大允许大小", code=3202, http_status=413)

    _ensure_upload_target(user, parent_id, department_id)

    # 已存在相同物理块：直接走秒传，无需分片
    if blob_service.find_usable(h, file_size) is not None:
        return {"instant": True}

    size = chunk_size or CHUNK_SIZE_DEFAULT
    if not CHUNK_SIZE_MIN <= size <= CHUNK_SIZE_MAX:
        raise ApiError(
            f"分片大小需在 {CHUNK_SIZE_MIN // 1024}KB~{CHUNK_SIZE_MAX // (1024 * 1024)}MB 之间",
            code=3208,
        )
    total = (file_size + size - 1) // size

    now = datetime.now(timezone.utc)
    # 断点恢复：同用户 + 同内容 + 同目标位置的有效会话直接复用
    existing = (
        db.session.query(UploadSession)
        .filter(
            UploadSession.user_id == user.id,
            UploadSession.file_hash == h,
            UploadSession.file_size == file_size,
            UploadSession.parent_id.is_(None) if parent_id is None
            else UploadSession.parent_id == parent_id,
            UploadSession.department_id.is_(None) if department_id is None
            else UploadSession.department_id == department_id,
            UploadSession.status == "uploading",
            UploadSession.expire_time > now,
        )
        .order_by(UploadSession.create_time.desc())
        .first()
    )
    if existing is not None:
        return {"instant": False, **existing.to_dict()}

    session = UploadSession(
        id=uuid.uuid4().hex,
        user_id=user.id,
        file_name=name,
        file_size=file_size,
        file_hash=h,
        chunk_size=size,
        total_chunks=total,
        parent_id=parent_id,
        department_id=department_id,
        status="uploading",
        create_time=now,
        expire_time=now + SESSION_TTL,
    )
    db.session.add(session)
    db.session.commit()
    return {"instant": False, **session.to_dict()}


def chunk_upload(
    user: User, upload_id: str, index: int, chunk_hash: str | None, file_storage
) -> dict:
    session = _get_owned_session(user, upload_id)
    if not isinstance(index, int) or not 0 <= index < session.total_chunks:
        raise ApiError("分片序号非法", code=3208)

    part_size, server_hash = storage_service.save_part(file_storage, upload_id, index)

    # 分片大小校验：非末片须等于 chunk_size，末片等于余数
    expect = session.chunk_size if index < session.total_chunks - 1 else (
        session.file_size - session.chunk_size * (session.total_chunks - 1)
    )
    if part_size != expect:
        storage_service.remove_physical(str(storage_service.part_path(upload_id, index)))
        raise ApiError(
            f"分片 {index} 大小不符：期望 {expect}，实际 {part_size}", code=3208
        )
    if chunk_hash and blob_service.normalize_hash(chunk_hash) != server_hash:
        storage_service.remove_physical(str(storage_service.part_path(upload_id, index)))
        raise ApiError(f"分片 {index} 指纹校验失败", code=3209)

    row = (
        db.session.query(UploadChunk)
        .filter(UploadChunk.session_id == upload_id, UploadChunk.chunk_index == index)
        .first()
    )
    if row is None:
        row = UploadChunk(
            session_id=upload_id, chunk_index=index,
            chunk_size=part_size, chunk_hash=server_hash,
        )
        db.session.add(row)
    else:
        row.chunk_size = part_size
        row.chunk_hash = server_hash
        row.create_time = datetime.now(timezone.utc)
    db.session.commit()
    return {
        "index": index,
        "received_count": session.chunks.count(),
        "total_chunks": session.total_chunks,
    }


def chunk_complete(user: User, upload_id: str) -> dict:
    session = _get_owned_session(user, upload_id)
    rows = (
        db.session.query(UploadChunk)
        .filter(UploadChunk.session_id == upload_id)
        .order_by(UploadChunk.chunk_index.asc())
        .all()
    )
    indexes = [r.chunk_index for r in rows]
    if len(rows) != session.total_chunks or indexes != list(range(session.total_chunks)):
        raise ApiError(
            f"分片不完整：已收 {len(rows)}/{session.total_chunks}", code=3210
        )
    if sum(r.chunk_size for r in rows) != session.file_size:
        raise ApiError("分片总大小与文件大小不一致", code=3210)

    staged_path, total_size, merged_hash = storage_service.merge_parts(
        upload_id, indexes
    )
    if merged_hash != session.file_hash:
        storage_service.remove_staging(staged_path)
        session.status = "aborted"
        db.session.commit()
        raise ApiError("文件指纹校验失败，分片可能损坏，请重新上传", code=3205)

    suffix = storage_service.extract_suffix(session.file_name)
    node = _commit_new_file(
        user, session.parent_id, session.department_id, session.file_name, suffix,
        total_size, merged_hash, staged_path, action="file_upload",
    )

    # 成功后清理会话（节点已提交；清理失败留给 GC 兜底）
    db.session.query(UploadChunk).filter(
        UploadChunk.session_id == upload_id
    ).delete(synchronize_session=False)
    db.session.delete(session)
    db.session.commit()
    storage_service.remove_session_dir(upload_id)
    return {"node": node.to_dict()}


def chunk_abort(user: User, upload_id: str) -> dict:
    session = _get_owned_session(user, upload_id, active_only=False)
    db.session.query(UploadChunk).filter(
        UploadChunk.session_id == upload_id
    ).delete(synchronize_session=False)
    session.status = "aborted"
    db.session.delete(session)
    db.session.commit()
    storage_service.remove_session_dir(upload_id)
    return {"aborted": True}


def chunk_status(user: User, upload_id: str) -> dict:
    session = _get_owned_session(user, upload_id, active_only=False)
    return session.to_dict()


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
    """删除节点：回收站开启时软删（可恢复），关闭时立即彻底删除。"""
    node = get_owned_node(user, node_id, required="delete")
    if setting_service.is_trash_enabled():
        trash_service.soft_delete(user, node)
    else:
        trash_service.hard_delete(node, actor_id=user.id)
    db.session.refresh(user)


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
