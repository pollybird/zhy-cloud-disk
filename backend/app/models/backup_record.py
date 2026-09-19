"""备份记录：手动/定时备份的执行记录与产物位置（本地 / 远端）。"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BackupRecord(db.Model):
    __tablename__ = "backup_record"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False, unique=True)
    file_size = db.Column(db.BigInteger, nullable=False, default=0)
    db_type = db.Column(db.String(16), nullable=False, default="sqlite")
    trigger = db.Column(db.String(16), nullable=False, default="manual")  # manual/schedule
    status = db.Column(db.String(16), nullable=False, default="running")  # running/done/failed
    location = db.Column(db.String(16), nullable=False, default="local")  # local/remote
    remote_target = db.Column(db.String(255), nullable=True)
    message = db.Column(db.String(500), nullable=True)
    create_time = db.Column(db.DateTime, nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "file_size": self.file_size,
            "db_type": self.db_type,
            "trigger": self.trigger,
            "status": self.status,
            "location": self.location,
            "remote_target": self.remote_target,
            "message": self.message,
            "create_time": self.create_time.isoformat() if self.create_time else None,
        }
