"""文件分享表：公开/加密分享、有效期、访问统计。"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Share(db.Model):
    __tablename__ = "share"
    __table_args__ = (
        db.Index("ix_share_status_expire", "status", "expire_time"),
    )

    id = db.Column(db.Integer, primary_key=True)
    file_id = db.Column(
        db.Integer, db.ForeignKey("file_node.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    share_code = db.Column(db.String(64), unique=True, nullable=False, index=True)
    share_pwd = db.Column(db.String(255), nullable=True)  # 空=公开分享
    expire_time = db.Column(db.DateTime, nullable=True, index=True)  # 空=永久
    create_time = db.Column(db.DateTime, nullable=False, default=_utcnow)
    view_count = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(
        db.String(16), nullable=False, default="active", index=True
    )  # active/expired/cancelled

    file = db.relationship("FileNode", lazy="joined")
    user = db.relationship("User", lazy="joined")

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expire_time is None:
            return False
        now = now or datetime.now(timezone.utc)
        expire = self.expire_time
        if expire.tzinfo is None:
            from datetime import timezone as _tz

            expire = expire.replace(tzinfo=_tz.utc)
        return now > expire

    def to_dict(self, include_code: bool = True) -> dict:
        return {
            "id": self.id,
            "file_id": self.file_id,
            "file_name": self.file.file_name if self.file else None,
            "file_size": self.file.file_size if self.file else None,
            "is_folder": self.file.is_folder if self.file else False,
            "user_id": self.user_id,
            "share_code": self.share_code if include_code else None,
            "has_password": bool(self.share_pwd),
            "expire_time": self.expire_time.isoformat() if self.expire_time else None,
            "create_time": self.create_time.isoformat() if self.create_time else None,
            "view_count": self.view_count,
            "status": self.status,
        }
