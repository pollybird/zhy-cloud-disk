"""插件注册表：持久化已发现插件的元信息与启用/禁用状态。"""
from datetime import datetime, timezone

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PluginRecord(db.Model):
    __tablename__ = "plugin"

    id = db.Column(db.Integer, primary_key=True)
    # 插件唯一名（小写字母/数字/连字符），与插件代码中的 name 一致
    name = db.Column(db.String(64), unique=True, nullable=False, index=True)
    version = db.Column(db.String(32), nullable=False, default="0.0.0")
    author = db.Column(db.String(128), nullable=False, default="")
    description = db.Column(db.String(500), nullable=False, default="")
    # 声明支持的文件后缀（小写、不带点），JSON 数组字符串
    supported_exts = db.Column(db.Text, nullable=False, default="[]")
    # 预览渲染类型：none/image/video/pdf/text/iframe
    preview_type = db.Column(db.String(16), nullable=False, default="none")
    # 来源：builtin（内置目录）/ external（外部 plugins/ 目录）
    source = db.Column(db.String(16), nullable=False, default="external")
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    # 最近一次扫描发现/加载失败的说明，空表示正常
    last_error = db.Column(db.String(500), nullable=False, default="")
    create_time = db.Column(db.DateTime, nullable=False, default=_utcnow)
    update_time = db.Column(
        db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def to_dict(self) -> dict:
        import json

        try:
            exts = json.loads(self.supported_exts or "[]")
        except json.JSONDecodeError:
            exts = []
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "supported_exts": exts,
            "preview_type": self.preview_type,
            "source": self.source,
            "enabled": self.enabled,
            "last_error": self.last_error,
            "update_time": self.update_time.isoformat() if self.update_time else None,
        }
