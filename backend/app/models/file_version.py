"""文件历史版本：覆盖保存时归档的旧内容（最近 N 个 + 保留 M 天）。

每条版本持有一次 blob 引用（计入 file_blob.ref_count），或指向 1.0/1.1
legacy 物理文件（非 blob 目录，删除时按 legacy 规则处理）。
"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FileVersion(db.Model):
    __tablename__ = "file_version"
    __table_args__ = (
        db.UniqueConstraint("node_id", "version_no", name="uk_version_node_no"),
        db.Index("ix_version_node_time", "node_id", "create_time"),
    )

    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(
        db.Integer,
        db.ForeignKey("file_node.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no = db.Column(db.Integer, nullable=False)
    file_hash = db.Column(db.String(40), nullable=True)
    file_size = db.Column(db.BigInteger, nullable=False, default=0)
    save_path = db.Column(db.String(500), nullable=False)
    operator_id = db.Column(db.Integer, nullable=True)
    create_time = db.Column(db.DateTime, nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "node_id": self.node_id,
            "version_no": self.version_no,
            "file_hash": self.file_hash,
            "file_size": self.file_size,
            "operator_id": self.operator_id,
            "create_time": self.create_time.isoformat() if self.create_time else None,
        }
