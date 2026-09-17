"""文件/文件夹统一表：邻接表模型实现目录层级。"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FileNode(db.Model):
    __tablename__ = "file_node"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "parent_id", "file_name", name="uk_user_parent_name"
        ),
        db.Index("ix_file_user_status", "user_id", "status"),
        db.Index("ix_file_user_suffix", "user_id", "file_suffix"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    department_id = db.Column(
        db.Integer, db.ForeignKey("department.id"), nullable=True, index=True
    )  # null=个人文件（1.0.0）；非 null=部门文件，user_id 记录上传者
    file_name = db.Column(db.String(255), nullable=False)
    file_suffix = db.Column(db.String(32), nullable=False, default="")
    file_size = db.Column(db.BigInteger, nullable=False, default=0)
    save_path = db.Column(db.String(500), nullable=True)  # 文件夹为空
    file_hash = db.Column(db.String(40), nullable=True, index=True)  # MD5 hex；旧数据为空
    is_folder = db.Column(db.Boolean, nullable=False, default=False)
    parent_id = db.Column(
        db.Integer,
        db.ForeignKey("file_node.id", ondelete="CASCADE"),
        nullable=True,
    )
    upload_time = db.Column(db.DateTime, nullable=False, default=_utcnow)
    status = db.Column(db.String(16), nullable=False, default="normal")  # normal/deleted

    parent = db.relationship(
        "FileNode", remote_side=[id], backref=db.backref("children", lazy="dynamic")
    )

    def to_dict(self, include_path: bool = False) -> dict:
        data = {
            "id": self.id,
            "user_id": self.user_id,
            "department_id": self.department_id,
            "file_name": self.file_name,
            "file_suffix": self.file_suffix,
            "file_size": self.file_size,
            "is_folder": self.is_folder,
            "parent_id": self.parent_id,
            "upload_time": self.upload_time.isoformat() if self.upload_time else None,
            "status": self.status,
        }
        if include_path:
            data["save_path"] = self.save_path
        return data
