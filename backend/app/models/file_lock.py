"""部门文件排他编辑锁（1.2.0）。

一个文件同时只能被一个用户锁定：持有者可编辑保存，其他读写用户降级为只读。
锁带过期时间（客户端心跳续约），客户端崩溃后锁自动失效，无需人工介入。
仅部门文件（file_node.department_id 非空）加锁，个人文件不使用此机制。
"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FileLock(db.Model):
    __tablename__ = "file_lock"

    # 一个文件最多一把锁：node_id 即主键，CASCADE 随文件删除
    node_id = db.Column(
        db.Integer,
        db.ForeignKey("file_node.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 冗余用户名，列表展示持有者无需再 join
    user_name = db.Column(db.String(64), nullable=False)
    create_time = db.Column(db.DateTime, nullable=False, default=_utcnow)
    renew_time = db.Column(db.DateTime, nullable=False, default=_utcnow)
    expire_time = db.Column(db.DateTime, nullable=False, index=True)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "create_time": self.create_time.isoformat() if self.create_time else None,
            "renew_time": self.renew_time.isoformat() if self.renew_time else None,
            "expire_time": self.expire_time.isoformat() if self.expire_time else None,
        }
