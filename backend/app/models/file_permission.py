"""文件权限授权：按部门或文件夹粒度，授予用户只读/读写/禁止访问权限。

权限优先级规则：
  1. 超级管理员 → 全权
  2. 部门管理员（scope=self_and_sub，含祖先部门）→ 全权
  3. denied（禁止访问）→ 最高优先级，屏蔽一切
  4. read_write → 可读可写
  5. read_only → 仅可读
  6. 无显式权限且为部门成员 → 默认 read_only
  7. 其他 → 拒绝
"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FilePermission(db.Model):
    __tablename__ = "file_permission"
    __table_args__ = (
        db.Index("ix_perm_user_dept", "user_id", "department_id"),
        db.Index("ix_perm_folder", "folder_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    department_id = db.Column(
        db.Integer, db.ForeignKey("department.id", ondelete="CASCADE"), nullable=True
    )
    folder_id = db.Column(
        db.Integer, db.ForeignKey("file_node.id", ondelete="CASCADE"), nullable=True
    )
    permission = db.Column(db.String(16), nullable=False)  # read_only / read_write / denied
    granted_by = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )
    granted_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    expire_time = db.Column(db.DateTime, nullable=True)  # null=永久

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "department_id": self.department_id,
            "folder_id": self.folder_id,
            "permission": self.permission,
            "granted_by": self.granted_by,
            "granted_at": self.granted_at.isoformat() if self.granted_at else None,
            "expire_time": self.expire_time.isoformat() if self.expire_time else None,
        }
