"""运行期轻量迁移：db.create_all() 不给现存表加列，这里手动补。"""
from sqlalchemy import inspect, text

from ..extensions import db


def ensure_file_hash_column() -> None:
    """file_node 表增加 file_hash 列（幂等）。"""
    inspector = inspect(db.engine)
    cols = {c["name"] for c in inspector.get_columns("file_node")}
    if "file_hash" not in cols:
        db.session.execute(
            text("ALTER TABLE file_node ADD COLUMN file_hash VARCHAR(40) NULL")
        )
        db.session.execute(
            text("CREATE INDEX ix_file_hash ON file_node (file_hash)")
        )
        db.session.commit()


def ensure_department_columns() -> None:
    """1.1.0 迁移：file_node 加 department_id，user 加 primary_department_id（幂等）。"""
    inspector = inspect(db.engine)

    file_cols = {c["name"] for c in inspector.get_columns("file_node")}
    if "department_id" not in file_cols:
        db.session.execute(
            text("ALTER TABLE file_node ADD COLUMN department_id INTEGER NULL")
        )
        db.session.execute(
            text("CREATE INDEX ix_file_dept ON file_node (department_id)")
        )

    user_cols = {c["name"] for c in inspector.get_columns("user")}
    if "primary_department_id" not in user_cols:
        db.session.execute(
            text("ALTER TABLE user ADD COLUMN primary_department_id INTEGER NULL")
        )

    db.session.commit()


def ensure_v130_columns() -> None:
    """1.3.0 迁移：file_node 加 deleted_time/delete_operator_id，user 加 last_active_time（幂等）。"""
    inspector = inspect(db.engine)

    file_cols = {c["name"] for c in inspector.get_columns("file_node")}
    if "deleted_time" not in file_cols:
        db.session.execute(
            text("ALTER TABLE file_node ADD COLUMN deleted_time DATETIME NULL")
        )
        db.session.execute(
            text("CREATE INDEX ix_file_deleted_time ON file_node (deleted_time)")
        )
    if "delete_operator_id" not in file_cols:
        db.session.execute(
            text("ALTER TABLE file_node ADD COLUMN delete_operator_id INTEGER NULL")
        )

    user_cols = {c["name"] for c in inspector.get_columns("user")}
    if "last_active_time" not in user_cols:
        db.session.execute(
            text("ALTER TABLE user ADD COLUMN last_active_time DATETIME NULL")
        )
        db.session.execute(
            text("CREATE INDEX ix_user_last_active ON user (last_active_time)")
        )

    db.session.commit()
