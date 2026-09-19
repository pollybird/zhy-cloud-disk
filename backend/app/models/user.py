"""用户表：账号信息、角色、存储配额。"""
from datetime import datetime, timezone

from ..extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(128), unique=True, nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False, default="user")  # admin/user
    primary_department_id = db.Column(
        db.Integer, db.ForeignKey("department.id"), nullable=True
    )  # 用户主属部门；null=无部门归属（纯个人用户）
    total_storage = db.Column(db.BigInteger, nullable=False, default=5 * 1024 ** 3)
    used_storage = db.Column(db.BigInteger, nullable=False, default=0)
    create_time = db.Column(db.DateTime, nullable=False, default=utcnow)
    status = db.Column(db.String(16), nullable=False, default="active")  # active/disabled
    last_active_time = db.Column(db.DateTime, nullable=True, index=True)  # 1.3.0 在线统计

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "primary_department_id": self.primary_department_id,
            "total_storage": self.total_storage,
            "used_storage": self.used_storage,
            "create_time": self.create_time.isoformat() if self.create_time else None,
            "status": self.status,
        }
