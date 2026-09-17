"""权限管理业务逻辑：管理员委派、成员权限授予/撤销、文件访问权限检查。

权限优先级：
  1. 超级管理员 → 全权
  2. 部门管理员（scope=self_and_sub，含祖先）→ 全权
  3. denied → 最高优先级，屏蔽一切
  4. read_write → 可读可写
  5. read_only → 仅可读
  6. 无显式权限且为部门成员 → 默认 read_only
  7. 其他 → 拒绝
"""
from datetime import datetime, timezone

from ..extensions import db
from ..models.department import Department, DepartmentAdmin, DepartmentMember
from ..models.file_node import FileNode
from ..models.file_permission import FilePermission
from ..models.user import User
from ..utils.errors import ApiError
from . import department_service
from . import log_service

VALID_PERMISSIONS = {"read_only", "read_write", "denied"}


# ---------------------------------------------------------------------------
# 管理员委派
# ---------------------------------------------------------------------------

def grant_admin(
    dept_id: int, user_id: int, scope: str, operator: User
) -> DepartmentAdmin:
    """委派部门管理员。仅超管或父部门管理员(scope=self_and_sub)可委派。"""
    dept = department_service._get_dept(dept_id)
    if scope not in ("self", "self_and_sub"):
        raise ApiError("scope 必须为 self 或 self_and_sub", code=3401)

    if not department_service.is_super_admin(operator):
        # 非超管：必须是父部门管理员（不能给自己部门委派——那需要父级权限）
        if dept.parent_id is None:
            raise ApiError("仅超级管理员可委派根部门管理员", code=3402, http_status=403)
        if not department_service.can_manage_department(dept.parent_id, operator):
            raise ApiError("无权委派该部门的管理员", code=3402, http_status=403)

    target = db.session.get(User, int(user_id))
    if target is None:
        raise ApiError("用户不存在", code=3403, http_status=404)

    existing = (
        db.session.query(DepartmentAdmin)
        .filter(
            DepartmentAdmin.department_id == dept_id,
            DepartmentAdmin.user_id == user_id,
        )
        .first()
    )
    if existing:
        existing.scope = scope
        existing.granted_by = operator.id
        db.session.commit()
    else:
        admin = DepartmentAdmin(
            department_id=dept_id,
            user_id=user_id,
            scope=scope,
            granted_by=operator.id,
        )
        db.session.add(admin)
        db.session.commit()

    log_service.record(
        operator.id, "admin_grant", "user", user_id, dept_id,
        {"scope": scope, "department_name": dept.name},
    )
    return db.session.query(DepartmentAdmin).filter(
        DepartmentAdmin.department_id == dept_id,
        DepartmentAdmin.user_id == user_id,
    ).first()


def revoke_admin(dept_id: int, user_id: int, operator: User) -> None:
    """撤销部门管理员。"""
    department_service._get_dept(dept_id)
    if not department_service.is_super_admin(operator):
        dept = db.session.get(Department, dept_id)
        if dept is None:
            raise ApiError("部门不存在", code=3301, http_status=404)
        if dept.parent_id is None:
            raise ApiError("仅超级管理员可撤销根部门管理员", code=3402, http_status=403)
        if not department_service.can_manage_department(dept.parent_id, operator):
            raise ApiError("无权撤销该部门的管理员", code=3402, http_status=403)

    admin = (
        db.session.query(DepartmentAdmin)
        .filter(
            DepartmentAdmin.department_id == dept_id,
            DepartmentAdmin.user_id == user_id,
        )
        .first()
    )
    if admin is None:
        raise ApiError("该用户不是部门管理员", code=3404, http_status=404)
    db.session.delete(admin)
    db.session.commit()
    log_service.record(
        operator.id, "admin_revoke", "user", user_id, dept_id, {}
    )


def get_admins(dept_id: int) -> list[dict]:
    department_service._get_dept(dept_id)
    rows = (
        db.session.query(DepartmentAdmin, User)
        .join(User, DepartmentAdmin.user_id == User.id)
        .filter(DepartmentAdmin.department_id == dept_id)
        .all()
    )
    result = []
    for admin, u in rows:
        result.append({
            **admin.to_dict(),
            "username": u.username,
            "email": u.email,
        })
    return result


def is_department_admin(dept_id: int, user: User) -> bool:
    """是否为指定部门的管理员（scope=self）。"""
    admin = (
        db.session.query(DepartmentAdmin)
        .filter(
            DepartmentAdmin.department_id == dept_id,
            DepartmentAdmin.user_id == user.id,
        )
        .first()
    )
    return admin is not None


def my_admin_depts(user: User) -> list[dict]:
    """当前用户被委派为管理员的部门列表（前端导航与按钮权限感知用）。"""
    rows = (
        db.session.query(DepartmentAdmin)
        .filter(DepartmentAdmin.user_id == user.id)
        .all()
    )
    return [{"department_id": r.department_id, "scope": r.scope} for r in rows]


# ---------------------------------------------------------------------------
# 成员权限授予/撤销
# ---------------------------------------------------------------------------

def grant_permission(
    user_id: int,
    dept_id: int | None,
    folder_id: int | None,
    permission: str,
    operator: User,
    expire_time: datetime | None = None,
) -> FilePermission:
    if permission not in VALID_PERMISSIONS:
        raise ApiError("权限类型不合法", code=3405)

    if dept_id:
        department_service._require_manage(dept_id, operator)
    if folder_id:
        folder = db.session.get(FileNode, int(folder_id))
        if folder is None or not folder.is_folder:
            raise ApiError("目标文件夹不存在或不是文件夹", code=3406, http_status=404)
        # 文件夹必须属于该部门
        if dept_id and folder.department_id != dept_id:
            raise ApiError("文件夹不属于该部门", code=3407, http_status=409)

    target = db.session.get(User, int(user_id))
    if target is None:
        raise ApiError("用户不存在", code=3403, http_status=404)

    # upsert：同 user+dept+folder 组合唯一
    existing = (
        db.session.query(FilePermission)
        .filter(
            FilePermission.user_id == user_id,
            FilePermission.department_id == dept_id,
            FilePermission.folder_id == folder_id,
        )
        .first()
    )
    if existing:
        existing.permission = permission
        existing.granted_by = operator.id
        existing.granted_at = datetime.now(timezone.utc)
        existing.expire_time = expire_time
        db.session.commit()
    else:
        perm = FilePermission(
            user_id=user_id,
            department_id=dept_id,
            folder_id=folder_id,
            permission=permission,
            granted_by=operator.id,
            expire_time=expire_time,
        )
        db.session.add(perm)
        db.session.commit()

    log_service.record(
        operator.id, "permission_grant", "permission", user_id, dept_id,
        {"permission": permission, "folder_id": folder_id, "expire_time": str(expire_time) if expire_time else None},
    )
    return db.session.query(FilePermission).filter(
        FilePermission.user_id == user_id,
        FilePermission.department_id == dept_id,
        FilePermission.folder_id == folder_id,
    ).first()


def revoke_permission(perm_id: int, operator: User) -> None:
    perm = db.session.get(FilePermission, int(perm_id))
    if perm is None:
        raise ApiError("权限记录不存在", code=3408, http_status=404)
    if perm.department_id:
        department_service._require_manage(perm.department_id, operator)
    elif not department_service.is_super_admin(operator):
        raise ApiError("无权撤销该权限", code=3402, http_status=403)
    dept_id = perm.department_id
    target_user_id = perm.user_id
    permission_value = perm.permission
    db.session.delete(perm)
    db.session.commit()
    log_service.record(
        operator.id, "permission_revoke", "permission", target_user_id, dept_id,
        {"permission": permission_value},
    )


def get_user_permissions(user_id: int) -> list[dict]:
    rows = (
        db.session.query(FilePermission)
        .filter(FilePermission.user_id == user_id)
        .all()
    )
    return [r.to_dict() for r in rows]


def get_department_permissions(dept_id: int, operator: User) -> list[dict]:
    department_service._require_manage(dept_id, operator)
    rows = (
        db.session.query(FilePermission, User)
        .join(User, FilePermission.user_id == User.id)
        .filter(FilePermission.department_id == dept_id)
        .all()
    )
    result = []
    for perm, u in rows:
        result.append({**perm.to_dict(), "username": u.username})
    return result


# ---------------------------------------------------------------------------
# 权限检查（核心）
# ---------------------------------------------------------------------------

def _active_rows(rows: list) -> list:
    """过滤已过期的权限记录（SQLite 取回的时间可能缺时区，按 UTC 处理）。"""
    now = datetime.now(timezone.utc)
    active = []
    for p in rows:
        if p.expire_time is None:
            active.append(p)
            continue
        expires = p.expire_time
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires > now:
            active.append(p)
    return active


def _perm_from_rows(active_perms: list) -> str | None:
    """按 denied > read_write > read_only 优先级，从有效授权行归纳权限；无行返回 None。"""
    if not active_perms:
        return None
    # denied 最高优先级
    if any(p.permission == "denied" for p in active_perms):
        return "none"
    if any(p.permission == "read_write" for p in active_perms):
        return "read_write"
    if any(p.permission == "read_only" for p in active_perms):
        return "read_only"
    return None


def effective_department_permission(user: User, dept_id: int) -> str:
    """用户对部门的有效权限：read_write / read_only / none（无权或 denied）。

    供前端权限感知 UI 与文件列表 access 标注使用。
    """
    if department_service.is_super_admin(user):
        return "read_write"

    # 部门管理员全权
    if department_service.can_manage_department(dept_id, user):
        return "read_write"

    perms = (
        db.session.query(FilePermission)
        .filter(
            FilePermission.user_id == user.id,
            FilePermission.department_id == dept_id,
            # 仅部门级授权（folder_id 为空）决定部门整体权限；
            # 文件夹级授权只作用于对应文件夹及其子树，不得污染部门级判定
            FilePermission.folder_id.is_(None),
        )
        .all()
    )
    resolved = _perm_from_rows(_active_rows(perms))
    if resolved is not None:
        return resolved

    # 无显式权限，部门成员默认 read_only
    is_member = (
        db.session.query(DepartmentMember)
        .filter(
            DepartmentMember.department_id == dept_id,
            DepartmentMember.user_id == user.id,
        )
        .first()
    )
    return "read_only" if is_member else "none"


def effective_node_permission(user: User, node: FileNode) -> str:
    """用户对具体文件/文件夹节点的有效权限：read_write / read_only / none。

    部门文件先沿父文件夹链查找最具体的文件夹级授权，再回退部门级权限。
    """
    if node.department_id is None:
        # 个人文件：owner 或超管可读写
        if node.user_id == user.id or department_service.is_super_admin(user):
            return "read_write"
        return "none"

    if department_service.is_super_admin(user):
        return "read_write"
    if department_service.can_manage_department(node.department_id, user):
        return "read_write"

    # 沿父文件夹链向上查找最近的有效文件夹级授权。
    # 文件夹授权对该文件夹自身及其内容同时生效（可进入、可向其中写入），
    # 因此文件夹节点从自身开始查找，文件节点从其父文件夹开始。
    folder_id = node.id if node.is_folder else node.parent_id
    seen = set()
    while folder_id and folder_id not in seen:
        seen.add(folder_id)
        folder_perms = (
            db.session.query(FilePermission)
            .filter(
                FilePermission.user_id == user.id,
                FilePermission.folder_id == folder_id,
            )
            .all()
        )
        resolved = _perm_from_rows(_active_rows(folder_perms))
        if resolved is not None:
            return resolved
        parent = db.session.get(FileNode, folder_id)
        if parent is None:
            break
        folder_id = parent.parent_id

    # 回退到部门级权限
    return effective_department_permission(user, node.department_id)


def check_department_access(user: User, dept_id: int, required: str) -> bool:
    """检查用户对部门的访问权限。required: read / write / delete"""
    perm = effective_department_permission(user, dept_id)
    if perm == "read_write":
        return True
    if perm == "read_only":
        return required == "read"
    return False


def check_file_access(user: User, node: FileNode, required: str) -> bool:
    """检查用户对文件节点的访问权限。required: read / write / delete"""
    perm = effective_node_permission(user, node)
    if perm == "read_write":
        return True
    if perm == "read_only":
        return required == "read"
    return False
