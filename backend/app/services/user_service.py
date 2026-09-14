"""用户管理业务：信息、改密、管理员用户管理。"""
from flask import current_app
from sqlalchemy import or_

from ..extensions import db
from ..models.user import User
from ..services import setting_service
from ..utils.errors import ApiError
from ..utils.security import hash_password, verify_password
from ..utils.validators import (
    validate_email,
    validate_password,
    validate_username,
)

ROLES = {"admin", "user"}
STATUSES = {"active", "disabled"}


def change_password(user: User, old_password: str, new_password: str) -> None:
    if not verify_password(old_password, user.password):
        raise ApiError("原密码不正确", code=1201)
    new_password = validate_password(new_password)
    if verify_password(new_password, user.password):
        raise ApiError("新密码不能与原密码相同", code=1202)
    user.password = hash_password(new_password)
    db.session.commit()


def list_users(keyword: str = "", page: int = 1, size: int = 20) -> dict:
    query = db.session.query(User)
    keyword = (keyword or "").strip()
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            or_(User.username.like(like), User.email.like(like))
        )
    total = query.count()
    rows = (
        query.order_by(User.id.asc())
        .offset(max(page - 1, 0) * size)
        .limit(size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [u.to_dict() for u in rows],
    }


def update_quota(admin: User, user_id: int, total_storage: int) -> User:
    try:
        total_storage = int(total_storage)
    except (TypeError, ValueError):
        raise ApiError("存储配额必须为整数（字节）", code=1203)
    if total_storage <= 0:
        raise ApiError("存储配额必须大于 0", code=1203)

    user = db.session.get(User, user_id)
    if user is None:
        raise ApiError("用户不存在", code=1204, http_status=404)
    if total_storage < user.used_storage:
        raise ApiError("新配额不能小于该用户已使用空间", code=1205)
    user.total_storage = total_storage
    db.session.commit()
    return user


def set_user_status(admin: User, user_id: int, status: str) -> User:
    if status not in STATUSES:
        raise ApiError("非法的账号状态", code=1206)
    user = db.session.get(User, user_id)
    if user is None:
        raise ApiError("用户不存在", code=1204, http_status=404)
    if user.id == admin.id:
        raise ApiError("不能修改自己的启用状态", code=1210)
    if status == "disabled" and user.role == "admin" and _count_active_admins() <= 1:
        raise ApiError("至少需要保留一个启用状态的管理员", code=1211)
    user.status = status
    db.session.commit()
    return user


# ------------------------- 系统设置 -------------------------

def get_admin_settings() -> dict:
    return setting_service.admin_settings()


def update_admin_settings(payload: dict) -> dict:
    return setting_service.update_admin_settings(payload)


# ------------------------- 管理员建号/改号 -------------------------

def _count_active_admins() -> int:
    return (
        db.session.query(User)
        .filter(User.role == "admin", User.status == "active")
        .count()
    )


def _ensure_unique(username: str, email: str, exclude_id: int | None = None) -> None:
    query = db.session.query(User).filter(
        or_(User.username == username, User.email == email)
    )
    if exclude_id is not None:
        query = query.filter(User.id != exclude_id)
    if query.first():
        raise ApiError("用户名或邮箱已存在", code=1101, http_status=409)


def admin_create_user(admin: User, payload: dict) -> User:
    """管理员后台创建用户：与自助注册相互独立，可指定角色与配额。"""
    username = validate_username(payload.get("username", ""))
    email = validate_email(payload.get("email", ""))
    password = validate_password(payload.get("password", ""))

    role = (payload.get("role") or "user").strip()
    if role not in ROLES:
        raise ApiError("角色必须为 admin 或 user", code=1209)

    status = (payload.get("status") or "active").strip()
    if status not in STATUSES:
        raise ApiError("非法的账号状态", code=1206)

    total_storage = _parse_quota(
        payload.get("total_storage"), int(current_app.config["DEFAULT_QUOTA"])
    )
    _ensure_unique(username, email)

    user = User(
        username=username,
        email=email,
        password=hash_password(password),
        role=role,
        status=status,
        total_storage=total_storage,
        used_storage=0,
    )
    db.session.add(user)
    db.session.commit()
    return user


def admin_update_user(admin: User, user_id: int, payload: dict) -> User:
    """管理员修改用户：邮箱/角色/状态/配额可局部更新，可重置密码。"""
    user = db.session.get(User, int(user_id))
    if user is None:
        raise ApiError("用户不存在", code=1204, http_status=404)

    is_self = user.id == admin.id

    if "email" in payload:
        email = validate_email(payload.get("email", ""))
        _ensure_unique(user.username, email, exclude_id=user.id)
        user.email = email

    if "role" in payload:
        role = (payload.get("role") or "").strip()
        if role not in ROLES:
            raise ApiError("角色必须为 admin 或 user", code=1209)
        if is_self:
            raise ApiError("不能修改自己的角色", code=1210)
        if role != "admin" and user.role == "admin" and user.status == "active":
            if _count_active_admins() <= 1:
                raise ApiError("至少需要保留一个启用状态的管理员", code=1211)
        user.role = role

    if "status" in payload:
        status = (payload.get("status") or "").strip()
        if status not in STATUSES:
            raise ApiError("非法的账号状态", code=1206)
        if is_self:
            raise ApiError("不能修改自己的启用状态", code=1210)
        if status == "disabled" and user.role == "admin":
            if _count_active_admins() <= 1:
                raise ApiError("至少需要保留一个启用状态的管理员", code=1211)
        user.status = status

    if "total_storage" in payload:
        total_storage = _parse_quota(payload.get("total_storage"), user.total_storage)
        if total_storage < user.used_storage:
            raise ApiError("新配额不能小于该用户已使用空间", code=1205)
        user.total_storage = total_storage

    new_password = payload.get("new_password")
    if new_password:
        if is_self:
            raise ApiError("请通过个人中心修改自己的密码", code=1213)
        user.password = hash_password(validate_password(new_password))

    db.session.commit()
    return user


def _parse_quota(value, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        total = int(value)
    except (TypeError, ValueError):
        raise ApiError("存储配额必须为整数（字节）", code=1203)
    if total <= 0:
        raise ApiError("存储配额必须大于 0", code=1203)
    return total
