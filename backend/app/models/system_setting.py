"""系统设置表：键值对存储运行期可由管理员调整的全局配置（如注册开关）。"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SystemSetting(db.Model):
    __tablename__ = "system_setting"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(255), nullable=False, default="")
    update_time = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
