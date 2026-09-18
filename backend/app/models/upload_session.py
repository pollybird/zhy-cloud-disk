"""分片上传会话与分片记录（大文件断点续传）。

UploadSession  一次分片上传的元数据（uuid 主键，24h 过期）
UploadChunk    已落盘的分片序号与校验信息（tmp/uploads/<session>/<index>.part）
"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UploadSession(db.Model):
    __tablename__ = "upload_session"
    __table_args__ = (
        db.Index("ix_upload_session_user_hash", "user_id", "file_hash"),
        db.Index("ix_upload_session_expire", "expire_time"),
    )

    id = db.Column(db.String(36), primary_key=True)  # uuid4 hex
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    file_name = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.BigInteger, nullable=False, default=0)
    file_hash = db.Column(db.String(40), nullable=False)
    chunk_size = db.Column(db.Integer, nullable=False)
    total_chunks = db.Column(db.Integer, nullable=False)
    parent_id = db.Column(db.Integer, nullable=True)
    department_id = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(16), nullable=False, default="uploading")
    # uploading / completed / aborted
    create_time = db.Column(db.DateTime, nullable=False, default=_utcnow)
    expire_time = db.Column(db.DateTime, nullable=False)

    chunks = db.relationship(
        "UploadChunk",
        backref="session",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def received_indexes(self) -> list[int]:
        return [
            c.chunk_index
            for c in self.chunks.order_by(UploadChunk.chunk_index.asc()).all()
        ]

    def to_dict(self) -> dict:
        return {
            "upload_id": self.id,
            "file_name": self.file_name,
            "file_size": self.file_size,
            "chunk_size": self.chunk_size,
            "total_chunks": self.total_chunks,
            "received": self.received_indexes(),
            "status": self.status,
        }


class UploadChunk(db.Model):
    __tablename__ = "upload_chunk"
    __table_args__ = (
        db.UniqueConstraint("session_id", "chunk_index", name="uk_session_chunk"),
    )

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.String(36),
        db.ForeignKey("upload_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index = db.Column(db.Integer, nullable=False)
    chunk_size = db.Column(db.BigInteger, nullable=False, default=0)
    chunk_hash = db.Column(db.String(40), nullable=True)
    create_time = db.Column(db.DateTime, nullable=False, default=_utcnow)
