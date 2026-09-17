"""部门管理接口：树查询、CRUD、成员管理。"""
from flask import Blueprint, request

from ..services import department_service
from ..utils.decorators import current_user, login_required
from ..utils.response import success

bp = Blueprint("department", __name__, url_prefix="/api/department")


@bp.get("/tree")
@login_required
def tree():
    return success(department_service.get_department_tree(current_user()))


@bp.post("")
@login_required
def create():
    data = request.get_json(silent=True) or {}
    dept = department_service.create_department(
        data.get("name", ""),
        data.get("parent_id"),
        current_user(),
    )
    return success(dept.to_dict(), msg="部门创建成功")


@bp.put("/<int:dept_id>")
@login_required
def update(dept_id: int):
    data = request.get_json(silent=True) or {}
    dept = department_service.update_department(
        dept_id,
        data.get("name"),
        data.get("sort_order"),
        current_user(),
        storage_quota=data.get("storage_quota"),
    )
    return success(dept.to_dict(), msg="部门更新成功")


@bp.delete("/<int:dept_id>")
@login_required
def delete(dept_id: int):
    department_service.delete_department(dept_id, current_user())
    return success(msg="部门删除成功")


@bp.post("/<int:dept_id>/move")
@login_required
def move(dept_id: int):
    data = request.get_json(silent=True) or {}
    dept = department_service.move_department(
        dept_id, data.get("new_parent_id"), current_user()
    )
    return success(dept.to_dict(), msg="部门迁移成功")


@bp.get("/<int:dept_id>/members")
@login_required
def members(dept_id: int):
    return success(department_service.get_members(dept_id, current_user()))


@bp.get("/<int:dept_id>/candidate-users")
@login_required
def candidate_users(dept_id: int):
    """可添加为成员的用户候选列表（排除已是成员的用户，最多 20 条）。"""
    keyword = request.args.get("keyword") or None
    return success(
        department_service.get_candidate_users(dept_id, keyword, current_user())
    )


@bp.post("/<int:dept_id>/members")
@login_required
def add_member(dept_id: int):
    data = request.get_json(silent=True) or {}
    member = department_service.add_member(
        dept_id,
        data.get("user_id"),
        data.get("position", ""),
        current_user(),
    )
    return success(member.to_dict(), msg="成员添加成功")


@bp.delete("/<int:dept_id>/members/<int:user_id>")
@login_required
def remove_member(dept_id: int, user_id: int):
    department_service.remove_member(dept_id, user_id, current_user())
    return success(msg="成员移除成功")


@bp.put("/<int:dept_id>/members/<int:user_id>")
@login_required
def update_member(dept_id: int, user_id: int):
    data = request.get_json(silent=True) or {}
    member = department_service.update_member(
        dept_id, user_id, data.get("position"), current_user()
    )
    return success(member.to_dict(), msg="成员更新成功")
