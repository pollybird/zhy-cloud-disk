"""审计日志接口：全局日志（超管）、部门日志（部门管理员）。"""
from flask import Blueprint, request

from ..services import log_service
from ..utils.decorators import admin_required, current_user, login_required
from ..utils.response import success

bp = Blueprint("log", __name__, url_prefix="/api/log")


def _paging_args() -> tuple[int, int]:
    try:
        page = max(int(request.args.get("page", 1)), 1)
        size = min(max(int(request.args.get("size", 20)), 1), 100)
    except (TypeError, ValueError):
        page, size = 1, 20
    return page, size


@bp.get("/global")
@admin_required
def global_logs():
    """全局操作日志（仅超级管理员）。"""
    page, size = _paging_args()
    return success(log_service.list_global_logs(
        page=page,
        size=size,
        action=request.args.get("action") or None,
        department_id=request.args.get("department_id") or None,
        user_id=request.args.get("user_id") or None,
    ))


@bp.get("/department/<int:dept_id>")
@login_required
def department_logs(dept_id: int):
    """部门及子部门操作日志（需部门管理权限）。"""
    page, size = _paging_args()
    return success(log_service.list_department_logs(
        current_user(),
        dept_id,
        page=page,
        size=size,
        action=request.args.get("action") or None,
        user_id=request.args.get("user_id") or None,
    ))
