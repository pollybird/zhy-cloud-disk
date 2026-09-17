"""部门组织架构：无限级树状结构、成员、分级管理员。

Department          部门（parent_id 自引用，无限级）
DepartmentMember    部门成员（员工归属）
DepartmentAdmin     部门管理员（scope: self / self_and_sub，分级委派）
"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Department(db.Model):
    __tablename__ = "department"
    __table_args__ = (
        db.UniqueConstraint("parent_id", "name", name="uk_parent_dept_name"),
        db.Index("ix_dept_parent", "parent_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    parent_id = db.Column(
        db.Integer,
        db.ForeignKey("department.id", ondelete="CASCADE"),
        nullable=True,
    )
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(16), nullable=False, default="active")  # active/disabled
    storage_quota = db.Column(db.BigInteger, nullable=False, default=0)  # 0=不限
    used_storage = db.Column(db.BigInteger, nullable=False, default=0)
    create_time = db.Column(db.DateTime, nullable=False, default=_utcnow)
    created_by = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )

    parent = db.relationship(
        "Department", remote_side=[id], backref=db.backref("children", lazy="dynamic")
    )

    def to_dict(self, include_children: bool = False) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "sort_order": self.sort_order,
            "status": self.status,
            "storage_quota": self.storage_quota,
            "used_storage": self.used_storage,
            "create_time": self.create_time.isoformat() if self.create_time else None,
            "created_by": self.created_by,
        }
        if include_children:
            data["children"] = [c.to_dict(include_children=True) for c in self.children]
        return data


class DepartmentMember(db.Model):
    __tablename__ = "department_member"
    __table_args__ = (
        db.UniqueConstraint("department_id", "user_id", name="uk_dept_user"),
        db.Index("ix_dept_member_user", "user_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(
        db.Integer, db.ForeignKey("department.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    position = db.Column(db.String(64), nullable=False, default="")
    join_time = db.Column(db.DateTime, nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "department_id": self.department_id,
            "user_id": self.user_id,
            "position": self.position,
            "join_time": self.join_time.isoformat() if self.join_time else None,
        }


class DepartmentAdmin(db.Model):
    __tablename__ = "department_admin"
    __table_args__ = (
        db.UniqueConstraint("department_id", "user_id", name="uk_dept_admin"),
        db.Index("ix_dept_admin_user", "user_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(
        db.Integer, db.ForeignKey("department.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    scope = db.Column(db.String(16), nullable=False, default="self_and_sub")  # self / self_and_sub
    granted_by = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )
    granted_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "department_id": self.department_id,
            "user_id": self.user_id,
            "scope": self.scope,
            "granted_by": self.granted_by,
            "granted_at": self.granted_at.isoformat() if self.granted_at else None,
        }
