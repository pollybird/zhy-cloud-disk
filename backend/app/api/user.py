"""用户接口：个人信息、改密、管理员用户管理。"""
from flask import Blueprint, request

from ..services import user_service
from ..utils.decorators import admin_required, current_user, login_required
from ..utils.response import success

bp = Blueprint("user", __name__, url_prefix="/api")


@bp.get("/user/info")
@login_required
def user_info():
    return success({"user": current_user().to_dict()})


@bp.put("/user/pwd")
@login_required
def change_password():
    data = request.get_json(silent=True) or {}
    user_service.change_password(
        current_user(),
        data.get("old_password", ""),
        data.get("new_password", ""),
    )
    return success(msg="密码修改成功")


# ------------------------- 管理员 -------------------------

@bp.get("/admin/users")
@admin_required
def admin_list_users():
    keyword = request.args.get("q", "")
    page = max(int(request.args.get("page", 1)), 1)
    size = min(max(int(request.args.get("size", 20)), 1), 100)
    return success(user_service.list_users(keyword, page, size))


@bp.get("/admin/settings")
@admin_required
def admin_get_settings():
    return success(user_service.get_admin_settings())


@bp.put("/admin/settings")
@admin_required
def admin_update_settings():
    payload = request.get_json(silent=True) or {}
    return success(user_service.update_admin_settings(payload), msg="设置已保存")


@bp.post("/admin/users")
@admin_required
def admin_create_user():
    payload = request.get_json(silent=True) or {}
    user = user_service.admin_create_user(current_user(), payload)
    return success({"user": user.to_dict()}, msg="用户创建成功")


@bp.put("/admin/users/<int:user_id>")
@admin_required
def admin_update_user(user_id: int):
    payload = request.get_json(silent=True) or {}
    user = user_service.admin_update_user(current_user(), user_id, payload)
    return success({"user": user.to_dict()}, msg="用户信息已更新")


@bp.put("/admin/users/<int:user_id>/quota")
@admin_required
def admin_update_quota(user_id: int):
    data = request.get_json(silent=True) or {}
    user = user_service.update_quota(
        current_user(), user_id, data.get("total_storage")
    )
    return success({"user": user.to_dict()}, msg="配额已更新")


@bp.put("/admin/users/<int:user_id>/status")
@admin_required
def admin_set_status(user_id: int):
    data = request.get_json(silent=True) or {}
    user = user_service.set_user_status(
        current_user(), user_id, data.get("status", "")
    )
    return success({"user": user.to_dict()}, msg="状态已更新")
