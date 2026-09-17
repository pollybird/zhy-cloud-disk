"""操作审计日志：记录与查询。

record() 为尽力而为（best-effort）：日志写入失败时静默回滚，绝不影响业务操作。
记录范围：部门文件操作（1.1.0）、权限变更、管理员委派、部门与成员管理。
"""
import json
from datetime import datetime, timezone

from flask import has_request_context, request

from ..extensions import db
from ..models.operation_log import OperationLog
from ..models.user import User

ACTIONS = {
    "department_create", "department_update", "department_delete", "department_move",
    "member_add", "member_remove", "member_update",
    "admin_grant", "admin_revoke",
    "permission_grant", "permission_revoke",
    "file_upload", "file_overwrite", "folder_create", "file_rename", "file_move", "file_delete",
}


def record(
    user_id: int,
    action: str,
    target_type: str,
    target_id: int | None = None,
    department_id: int | None = None,
    detail: dict | None = None,
) -> None:
    """写入一条操作日志（尽力而为，失败静默回滚，不影响业务）。"""
    try:
        ip = request.remote_addr if has_request_context() else None
        db.session.add(OperationLog(
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=int(target_id) if target_id is not None else None,
            department_id=int(department_id) if department_id else None,
            detail=json.dumps(detail, ensure_ascii=False, default=str) if detail else None,
            ip_address=ip,
            create_time=datetime.now(timezone.utc),
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _serialize(rows) -> list[dict]:
    return [
        {**log.to_dict(), "username": username or f"#{log.user_id}"}
        for log, username in rows
    ]


def list_global_logs(
    page: int = 1, size: int = 20, action: str | None = None,
    department_id: int | None = None, user_id: int | None = None,
) -> dict:
    """全局日志查询（仅超级管理员，由 API 层校验）。"""
    query = db.session.query(OperationLog, User.username).outerjoin(
        User, OperationLog.user_id == User.id
    )
    if action:
        query = query.filter(OperationLog.action == action)
    if department_id:
        query = query.filter(OperationLog.department_id == int(department_id))
    if user_id:
        query = query.filter(OperationLog.user_id == int(user_id))

    total = query.count()
    rows = (
        query.order_by(OperationLog.create_time.desc(), OperationLog.id.desc())
        .offset(max(page - 1, 0) * size)
        .limit(size)
        .all()
    )
    return {"total": total, "page": page, "size": size, "items": _serialize(rows)}


def list_department_logs(
    user, dept_id: int, page: int = 1, size: int = 20, action: str | None = None,
    user_id: int | None = None,
) -> dict:
    """部门日志查询：本部门及子部门；需具备部门管理权限。"""
    from . import department_service

    department_service._get_dept(dept_id)
    department_service._require_manage(dept_id, user)
    dept_ids = sorted(department_service._subtree_dept_ids(dept_id))

    query = db.session.query(OperationLog, User.username).outerjoin(
        User, OperationLog.user_id == User.id
    ).filter(OperationLog.department_id.in_(dept_ids))
    if action:
        query = query.filter(OperationLog.action == action)
    if user_id:
        query = query.filter(OperationLog.user_id == int(user_id))

    total = query.count()
    rows = (
        query.order_by(OperationLog.create_time.desc(), OperationLog.id.desc())
        .offset(max(page - 1, 0) * size)
        .limit(size)
        .all()
    )
    return {"total": total, "page": page, "size": size, "items": _serialize(rows)}
