"""全局系统设置：键值持久化在数据库，未设置时回退到应用配置/默认值。

设置项：
- allow_register：是否允许游客公开注册
- 回收站/历史版本开关与保留策略（1.3.0）
- 备份策略与远端凭据（1.3.0；远端密码加密存储）

缓存策略：读取时优先从缓存（Redis/内存）取，未命中则查库并回填；
写入时同步更新缓存。缓存 TTL 60 秒，设置变更后多 worker 最多延迟 60 秒生效。
"""
from flask import current_app

from ..extensions import db
from ..models.system_setting import SystemSetting
from ..services.cache_service import cache_get, cache_set
from ..utils.crypto import SecretDecryptError, decrypt_secret, encrypt_secret
from ..utils.errors import ApiError

KEY_ALLOW_REGISTER = "allow_register"

# ---- 1.3.0 回收站 / 版本 ----
KEY_TRASH_ENABLED = "trash_enabled"
KEY_VERSION_ENABLED = "version_enabled"
KEY_TRASH_RETENTION_DAYS = "trash_retention_days"
KEY_VERSION_MAX_COUNT = "version_max_count"
KEY_VERSION_RETENTION_DAYS = "version_retention_days"

# ---- 1.3.0 备份 ----
KEY_BACKUP_ENABLED = "backup_enabled"
KEY_BACKUP_KEEP_COUNT = "backup_keep_count"
KEY_BACKUP_HOUR = "backup_hour"
KEY_BACKUP_TARGET = "backup_target"
KEY_BACKUP_PROTOCOL = "backup_protocol"
KEY_BACKUP_HOST = "backup_host"
KEY_BACKUP_PORT = "backup_port"
KEY_BACKUP_USERNAME = "backup_username"
KEY_BACKUP_PASSWORD_ENC = "backup_password_enc"
KEY_BACKUP_REMOTE_DIR = "backup_remote_dir"

DEFAULT_TRASH_RETENTION_DAYS = 30
DEFAULT_VERSION_MAX_COUNT = 10
DEFAULT_VERSION_RETENTION_DAYS = 30
DEFAULT_BACKUP_KEEP_COUNT = 7
DEFAULT_BACKUP_HOUR = 3
DEFAULT_BACKUP_REMOTE_DIR = "/zhy-backups"

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


def _as_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    return raw.strip().lower() in _TRUE


def _get_bool(key: str, default: bool) -> bool:
    val = _as_bool(get_raw(key))
    return default if val is None else val


def _get_int(key: str, default: int) -> int:
    raw = get_raw(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 注册开关
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 回收站 / 版本策略
# ---------------------------------------------------------------------------

def is_trash_enabled() -> bool:
    return _get_bool(KEY_TRASH_ENABLED, True)


def is_version_enabled() -> bool:
    return _get_bool(KEY_VERSION_ENABLED, True)


def get_trash_retention_days() -> int:
    return _get_int(KEY_TRASH_RETENTION_DAYS, DEFAULT_TRASH_RETENTION_DAYS)


def get_version_policy() -> tuple[int, int]:
    """返回 (最大版本数, 版本保留天数)。"""
    return (
        _get_int(KEY_VERSION_MAX_COUNT, DEFAULT_VERSION_MAX_COUNT),
        _get_int(KEY_VERSION_RETENTION_DAYS, DEFAULT_VERSION_RETENTION_DAYS),
    )


# ---------------------------------------------------------------------------
# 备份策略
# ---------------------------------------------------------------------------

def is_backup_enabled() -> bool:
    return _get_bool(KEY_BACKUP_ENABLED, False)


def get_backup_schedule() -> dict:
    return {
        "enabled": is_backup_enabled(),
        "keep_count": _get_int(KEY_BACKUP_KEEP_COUNT, DEFAULT_BACKUP_KEEP_COUNT),
        "hour": _get_int(KEY_BACKUP_HOUR, DEFAULT_BACKUP_HOUR),
    }


def get_backup_remote_config() -> dict:
    """返回远端配置（含解密后的密码，仅供 backup_service 内部使用）。"""
    protocol = get_raw(KEY_BACKUP_PROTOCOL) or "sftp"
    port = _get_int(KEY_BACKUP_PORT, 22 if protocol == "sftp" else 21)
    enc = get_raw(KEY_BACKUP_PASSWORD_ENC) or ""
    password = ""
    if enc:
        try:
            password = decrypt_secret(enc, current_app.config["SECRET_KEY"])
        except SecretDecryptError:
            password = ""
    return {
        "target": get_raw(KEY_BACKUP_TARGET) or "local",
        "protocol": protocol,
        "host": get_raw(KEY_BACKUP_HOST) or "",
        "port": port,
        "username": get_raw(KEY_BACKUP_USERNAME) or "",
        "password": password,
        "remote_dir": get_raw(KEY_BACKUP_REMOTE_DIR) or DEFAULT_BACKUP_REMOTE_DIR,
        "has_password": bool(enc),
    }


# ---------------------------------------------------------------------------
# 管理员设置聚合
# ---------------------------------------------------------------------------

def admin_settings() -> dict:
    remote = get_backup_remote_config()
    return {
        "allow_register": is_register_allowed(),
        # 回收站 / 版本
        "trash_enabled": is_trash_enabled(),
        "version_enabled": is_version_enabled(),
        "trash_retention_days": get_trash_retention_days(),
        "version_max_count": get_version_policy()[0],
        "version_retention_days": get_version_policy()[1],
        # 备份
        "backup_enabled": is_backup_enabled(),
        "backup_keep_count": get_backup_schedule()["keep_count"],
        "backup_hour": get_backup_schedule()["hour"],
        "backup_target": remote["target"],
        "backup_protocol": remote["protocol"],
        "backup_host": remote["host"],
        "backup_port": remote["port"],
        "backup_username": remote["username"],
        "backup_remote_dir": remote["remote_dir"],
        "backup_has_password": remote["has_password"],
    }


def _require_int(payload: dict, key: str, setting_key: str, lo: int, hi: int,
                 writes: dict) -> None:
    if key not in payload:
        return
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(f"{key} 必须是整数", code=1221)
    if not lo <= value <= hi:
        raise ApiError(f"{key} 必须在 {lo}~{hi} 之间", code=1222)
    writes[setting_key] = str(value)


def _require_bool(payload: dict, key: str, setting_key: str, writes: dict) -> None:
    if key not in payload:
        return
    if not isinstance(payload[key], bool):
        raise ApiError(f"{key} 必须是布尔值", code=1221)
    writes[setting_key] = "true" if payload[key] else "false"


def update_admin_settings(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ApiError("请求体必须是对象", code=1221)

    # 第一阶段：全部校验通过后再统一写入，避免半写入
    writes: dict[str, str] = {}

    if "allow_register" in payload:
        if not isinstance(payload["allow_register"], bool):
            raise ApiError("allow_register 必须为布尔值", code=1220)
        writes[KEY_ALLOW_REGISTER] = "true" if payload["allow_register"] else "false"

    # 回收站 / 版本开关与保留策略
    _require_bool(payload, "trash_enabled", KEY_TRASH_ENABLED, writes)
    _require_bool(payload, "version_enabled", KEY_VERSION_ENABLED, writes)
    _require_int(payload, "trash_retention_days", KEY_TRASH_RETENTION_DAYS, 1, 365, writes)
    _require_int(payload, "version_max_count", KEY_VERSION_MAX_COUNT, 1, 100, writes)
    _require_int(payload, "version_retention_days", KEY_VERSION_RETENTION_DAYS, 1, 365, writes)

    # 备份策略
    _require_bool(payload, "backup_enabled", KEY_BACKUP_ENABLED, writes)
    _require_int(payload, "backup_keep_count", KEY_BACKUP_KEEP_COUNT, 1, 100, writes)
    _require_int(payload, "backup_hour", KEY_BACKUP_HOUR, 0, 23, writes)

    target = get_raw(KEY_BACKUP_TARGET) or "local"
    if "backup_target" in payload:
        target = payload["backup_target"]
        if target not in ("local", "remote"):
            raise ApiError("backup_target 只能是 local 或 remote", code=1222)
        writes[KEY_BACKUP_TARGET] = target

    remote_fields_present = any(
        k in payload
        for k in (
            "backup_protocol", "backup_host", "backup_port", "backup_username",
            "backup_password", "backup_remote_dir",
        )
    )
    # 只要请求涉及远端配置，或最终目标为远端，就走远端校验
    if remote_fields_present or target == "remote":
        _validate_remote_settings(payload, target, writes)

    # 第二阶段：统一落库
    for setting_key, value in writes.items():
        set_raw(setting_key, value)
    if KEY_ALLOW_REGISTER in writes:
        current_app.config["ALLOW_REGISTER"] = writes[KEY_ALLOW_REGISTER] == "true"

    return admin_settings()


def _validate_remote_settings(payload: dict, target: str, writes: dict) -> None:
    # 协议：请求值优先，其次已保存值，默认 sftp
    protocol = payload.get("backup_protocol") or get_raw(KEY_BACKUP_PROTOCOL) or "sftp"
    if "backup_protocol" in payload and protocol not in ("sftp", "ftp"):
        raise ApiError("backup_protocol 只能是 sftp 或 ftp", code=1222)
    writes[KEY_BACKUP_PROTOCOL] = protocol
    default_port = 22 if protocol == "sftp" else 21

    # 端口
    port_stored = get_raw(KEY_BACKUP_PORT)
    if "backup_port" in payload:
        port = payload["backup_port"]
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ApiError("backup_port 必须是 1~65535 的整数", code=1222)
        writes[KEY_BACKUP_PORT] = str(port)
    elif port_stored is None:
        writes[KEY_BACKUP_PORT] = str(default_port)

    # 文本字段
    for key, setting_key in (
        ("backup_host", KEY_BACKUP_HOST),
        ("backup_username", KEY_BACKUP_USERNAME),
        ("backup_remote_dir", KEY_BACKUP_REMOTE_DIR),
    ):
        if key in payload:
            value = payload[key]
            if not isinstance(value, str):
                raise ApiError(f"{key} 必须是字符串", code=1221)
            writes[setting_key] = value.strip()

    # 密码：空字符串/不传 = 保持原密码不变
    if "backup_password" in payload and payload["backup_password"]:
        if not isinstance(payload["backup_password"], str):
            raise ApiError("backup_password 必须是字符串", code=1221)
        writes[KEY_BACKUP_PASSWORD_ENC] = encrypt_secret(
            payload["backup_password"], current_app.config["SECRET_KEY"])

    # 目标为远端时的完整性校验（密码允许为空，例如匿名 FTP）
    if target == "remote":
        host = writes.get(KEY_BACKUP_HOST, get_raw(KEY_BACKUP_HOST) or "")
        if not str(host).strip():
            raise ApiError("远端备份必须填写服务器地址", code=1223)
