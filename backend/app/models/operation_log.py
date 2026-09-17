"""操作审计日志：记录文件操作、权限变更、部门调整等全量操作。

部门管理员可查本部门及子部门日志，超级管理员可查全局日志。
"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OperationLog(db.Model):
    __tablename__ = "operation_log"
    __table_args__ = (
        db.Index("ix_oplog_user_time", "user_id", "create_time"),
        db.Index("ix_oplog_dept", "department_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )
    action = db.Column(db.String(64), nullable=False)  # upload/delete/move/permission_grant/...
    target_type = db.Column(db.String(32), nullable=False)  # file/folder/department/user/permission
    target_id = db.Column(db.Integer, nullable=True)
    department_id = db.Column(db.Integer, nullable=True)
    detail = db.Column(db.Text, nullable=True)  # JSON 详情
    ip_address = db.Column(db.String(64), nullable=True)
    create_time = db.Column(db.DateTime, nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "department_id": self.department_id,
            "detail": self.detail,
            "ip_address": self.ip_address,
            "create_time": self.create_time.isoformat() if self.create_time else None,
        }
