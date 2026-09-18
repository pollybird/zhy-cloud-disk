"""内容寻址物理块（blob）：跨用户/跨部门秒传与物理去重的底座。

一份物理内容只存一份于 storage/blobs/<hash前2位>/<hash>；
多个 FileNode 通过 save_path 指向同一 blob，ref_count 记录正常态引用数。
"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FileBlob(db.Model):
    __tablename__ = "file_blob"
    __table_args__ = (
        db.Index("ix_blob_hash_size", "file_hash", "file_size"),
    )

    id = db.Column(db.Integer, primary_key=True)
    file_hash = db.Column(db.String(40), nullable=False, unique=True)  # MD5 hex
    file_size = db.Column(db.BigInteger, nullable=False, default=0)
    save_path = db.Column(db.String(500), nullable=False)
    ref_count = db.Column(db.Integer, nullable=False, default=0)
    create_time = db.Column(db.DateTime, nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "file_hash": self.file_hash,
            "file_size": self.file_size,
            "ref_count": self.ref_count,
            "create_time": self.create_time.isoformat() if self.create_time else None,
        }
