"""下载日志：区分登录用户下载与分享匿名下载。"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DownloadLog(db.Model):
    __tablename__ = "download_log"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    file_id = db.Column(
        db.Integer,
        db.ForeignKey("file_node.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    share_id = db.Column(
        db.Integer,
        db.ForeignKey("share.id", ondelete="SET NULL"),
        nullable=True,
    )
    ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    create_time = db.Column(db.DateTime, nullable=False, default=_utcnow, index=True)
