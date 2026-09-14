"""全局系统设置：键值持久化在数据库，未设置时回退到应用配置/默认值。

设置项：
- allow_register：是否允许游客公开注册。私有云盘默认关闭，由管理员在后台开启。

缓存策略：读取时优先从缓存（Redis/内存）取，未命中则查库并回填；
写入时同步更新缓存。缓存 TTL 60 秒，设置变更后多 worker 最多延迟 60 秒生效。
"""
from flask import current_app

from ..extensions import db
from ..models.system_setting import SystemSetting
from ..services.cache_service import cache_get, cache_set
from ..utils.errors import ApiError

KEY_ALLOW_REGISTER = "allow_register"

_TRUE = {"1", "true", "yes", "on"}

# 缓存键
_CACHE_PREFIX = "setting:"
_CACHE_TTL = 60  # 秒


def _cache_key(key: str) -> str:
    return f"{_CACHE_PREFIX}{key}"


def get_raw(key: str) -> str | None:
    """读取设置值：缓存优先，未命中查库并回填。"""
    cached = cache_get(_cache_key(key))
    if cached is not None:
        return str(cached)
    row = db.session.get(SystemSetting, key)
    value = row.value if row else None
    if value is not None:
        cache_set(_cache_key(key), value, ttl=_CACHE_TTL)
    return value


def set_raw(key: str, value: str) -> None:
    """写入设置值并同步更新缓存。"""
    row = db.session.get(SystemSetting, key)
    if row is None:
        row = SystemSetting(key=key, value=str(value))
        db.session.add(row)
    else:
        row.value = str(value)
    db.session.commit()
    cache_set(_cache_key(key), str(value), ttl=_CACHE_TTL)


def _invalidate(key: str) -> None:
    cache_delete(_cache_key(key))


def _as_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    return raw.strip().lower() in _TRUE


def is_register_allowed() -> bool:
    """数据库显式设置优先；从未设置时回退安装配置/环境变量（默认关闭）。"""
    stored = _as_bool(get_raw(KEY_ALLOW_REGISTER))
    if stored is not None:
        return stored
    return bool(current_app.config.get("ALLOW_REGISTER", False))


def set_register_allowed(allowed: bool) -> bool:
    allowed = bool(allowed)
    set_raw(KEY_ALLOW_REGISTER, "true" if allowed else "false")
    # 同步当前进程配置，保证读取一致性
    current_app.config["ALLOW_REGISTER"] = allowed
    return allowed


def admin_settings() -> dict:
    return {"allow_register": is_register_allowed()}


def update_admin_settings(payload: dict) -> dict:
    if "allow_register" not in payload or not isinstance(
        payload["allow_register"], bool
    ):
        raise ApiError("allow_register 必须为布尔值", code=1220)
    allowed = set_register_allowed(payload["allow_register"])
    return {"allow_register": allowed}
