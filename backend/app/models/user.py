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
    total_storage = db.Column(db.BigInteger, nullable=False, default=5 * 1024 ** 3)
    used_storage = db.Column(db.BigInteger, nullable=False, default=0)
    create_time = db.Column(db.DateTime, nullable=False, default=utcnow)
    status = db.Column(db.String(16), nullable=False, default="active")  # active/disabled

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "total_storage": self.total_storage,
            "used_storage": self.used_storage,
            "create_time": self.create_time.isoformat() if self.create_time else None,
            "status": self.status,
        }
