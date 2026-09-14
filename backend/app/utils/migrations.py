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
