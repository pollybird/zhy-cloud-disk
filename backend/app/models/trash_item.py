"""回收站根条目：记录被软删的根节点（文件或文件夹）及其原始信息。

软删时 FileNode 子树统一置 status=deleted，根节点 file_name 改写为
`#trash<node_id>` 以释放 (user_id,parent_id,file_name) 唯一约束占用，
原名与原父目录保存在本表，供还原使用。
"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TrashItem(db.Model):
    __tablename__ = "trash_item"
    __table_args__ = (
        db.Index("ix_trash_owner", "owner_user_id", "department_id"),
        db.Index("ix_trash_expire", "expire_time"),
    )

    id = db.Column(db.Integer, primary_key=True)
    node_id = db.Column(
        db.Integer,
        db.ForeignKey("file_node.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    original_name = db.Column(db.String(255), nullable=False)
    original_parent_id = db.Column(db.Integer, nullable=True)
    owner_user_id = db.Column(db.Integer, nullable=False)
    department_id = db.Column(
        db.Integer,
        db.ForeignKey("department.id"),
        nullable=True,
        index=True,
    )  # null=个人文件；非 null=部门文件
    is_folder = db.Column(db.Boolean, nullable=False, default=False)
    total_size = db.Column(db.BigInteger, nullable=False, default=0)
    operator_id = db.Column(db.Integer, nullable=True)
    create_time = db.Column(db.DateTime, nullable=False, default=_utcnow)
    expire_time = db.Column(db.DateTime, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "node_id": self.node_id,
            "file_name": self.original_name,
            "original_parent_id": self.original_parent_id,
            "owner_user_id": self.owner_user_id,
            "department_id": self.department_id,
            "is_folder": self.is_folder,
            "file_size": self.total_size,
            "operator_id": self.operator_id,
            "delete_time": self.create_time.isoformat() if self.create_time else None,
            "expire_time": self.expire_time.isoformat() if self.expire_time else None,
        }
