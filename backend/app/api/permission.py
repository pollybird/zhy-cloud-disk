"""权限管理接口：管理员委派、成员权限授予/撤销、权限查询。"""
from flask import Blueprint, request

from ..services import permission_service
from ..utils.decorators import current_user, login_required
from ..utils.response import success

bp = Blueprint("permission", __name__, url_prefix="/api/permission")


# ---------------------------------------------------------------------------
# 管理员委派
# ---------------------------------------------------------------------------

@bp.post("/admin")
@login_required
def grant_admin():
    data = request.get_json(silent=True) or {}
    admin = permission_service.grant_admin(
        data.get("department_id"),
        data.get("user_id"),
        data.get("scope", "self_and_sub"),
        current_user(),
    )
    return success(admin.to_dict(), msg="管理员委派成功")


@bp.delete("/admin/<int:dept_id>/<int:user_id>")
@login_required
def revoke_admin(dept_id: int, user_id: int):
    permission_service.revoke_admin(dept_id, user_id, current_user())
    return success(msg="管理员撤销成功")


@bp.get("/admins/<int:dept_id>")
@login_required
def list_admins(dept_id: int):
    return success(permission_service.get_admins(dept_id))


# ---------------------------------------------------------------------------
# 成员权限授予/撤销
# ---------------------------------------------------------------------------

@bp.post("/grant")
@login_required
def grant_permission():
    data = request.get_json(silent=True) or {}
    perm = permission_service.grant_permission(
        data.get("user_id"),
        data.get("department_id"),
        data.get("folder_id"),
        data.get("permission"),
        current_user(),
        data.get("expire_time"),
    )
    return success(perm.to_dict(), msg="权限授予成功")


@bp.delete("/<int:perm_id>")
@login_required
def revoke_permission(perm_id: int):
    permission_service.revoke_permission(perm_id, current_user())
    return success(msg="权限撤销成功")


@bp.get("/department/<int:dept_id>")
@login_required
def dept_permissions(dept_id: int):
    return success(
        permission_service.get_department_permissions(dept_id, current_user())
    )


@bp.get("/my")
@login_required
def my_permissions():
    return success(permission_service.get_user_permissions(current_user().id))


@bp.get("/my-admin-depts")
@login_required
def my_admin_depts():
    """当前用户被委派管理的部门列表（前端权限感知）。"""
    return success(permission_service.my_admin_depts(current_user()))
