"""配置加载链：环境变量 > instance/config.installed.json > 代码默认值。"""
import json
import os
from datetime import timedelta
from pathlib import Path

ZHY_VERSION = "1.1.0"

# 后端根目录（backend/）
BASE_DIR = Path(__file__).resolve().parent.parent
# 运行期目录（安装配置、SQLite 数据文件）
INSTANCE_DIR = Path(os.environ.get("ZHY_INSTANCE_DIR", BASE_DIR / "instance"))
# 用户文件物理存储根目录（可被安装向导/环境变量覆盖）
DEFAULT_STORAGE_DIR = BASE_DIR / "storage"
# 安装向导落盘配置
INSTALLED_CONFIG_PATH = INSTANCE_DIR / "config.installed.json"

# 禁止上传的文件后缀（可执行文件 / 脚本）
DENIED_EXTENSIONS = {
    "exe", "bat", "cmd", "com", "scr", "msi", "vbs", "ps1",
    "sh", "bash", "py", "pyc", "pyo", "jar", "app", "dll", "so",
    "php", "jsp", "asp", "aspx", "js", "vb", "wsf",
}

# 各类文件分类（用于前端分类筛选与插件匹配）
CATEGORY_EXTENSIONS = {
    "image": {"jpg", "jpeg", "png", "gif", "webp", "bmp", "svg"},
    "video": {"mp4", "flv", "mov", "avi", "mkv", "webm", "wmv"},
    "document": {
        "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
        "txt", "md", "csv", "rtf",
    },
    "audio": {"mp3", "wav", "flac", "aac", "ogg", "m4a"},
    "archive": {"zip", "rar", "7z", "tar", "gz", "bz2"},
}


def _resolve_instance_dir() -> Path:
    """运行期解析实例目录（支持环境变量热切换，用于测试与多实例部署）。"""
    return Path(os.environ.get("ZHY_INSTANCE_DIR", str(INSTANCE_DIR)))


def _resolve_installed_config_path() -> Path:
    return _resolve_instance_dir() / "config.installed.json"


def _read_installed_config() -> dict:
    """读取安装向导落盘的配置；不存在或损坏时返回空字典。"""
    path = _resolve_installed_config_path()
    try:
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_config() -> dict:
    """构建 Flask 应用配置字典。"""
    installed = _read_installed_config()

    default_db_uri = f"sqlite:///{(_resolve_instance_dir() / 'preinstall.db').as_posix()}"
    database_uri = (
        os.environ.get("ZHY_DATABASE_URL")
        or installed.get("database_uri")
        or default_db_uri
    )
    storage_dir = (
        os.environ.get("ZHY_STORAGE_DIR")
        or installed.get("storage_dir")
        or str(DEFAULT_STORAGE_DIR)
    )
    secret_key = (
        os.environ.get("ZHY_SECRET_KEY")
        or installed.get("secret_key")
        or "dev-insecure-secret-please-run-setup"
    )
    jwt_secret_key = (
        os.environ.get("ZHY_JWT_SECRET_KEY")
        or installed.get("jwt_secret_key")
        or "dev-insecure-jwt-secret-please-run-setup"
    )

    default_quota = installed.get("default_quota", 5 * 1024 ** 3)
    try:
        default_quota = int(os.environ.get("ZHY_DEFAULT_QUOTA", default_quota))
    except (TypeError, ValueError):
        default_quota = 5 * 1024 ** 3

    max_upload = installed.get("max_upload_size", 2 * 1024 ** 3)
    try:
        max_upload = int(os.environ.get("ZHY_MAX_UPLOAD_SIZE", max_upload))
    except (TypeError, ValueError):
        max_upload = 2 * 1024 ** 3

    cors_raw = os.environ.get("ZHY_CORS_ORIGINS", "*")
    cors_origins = [o.strip() for o in cors_raw.split(",") if o.strip()] or "*"

    redis_url = (
        os.environ.get("ZHY_REDIS_URL")
        or installed.get("redis_url")
        or ""
    )

    return {
        "APP_VERSION": ZHY_VERSION,
        "ZHY_VERSION": ZHY_VERSION,
        "ENV": os.environ.get("ZHY_ENV", "production"),
        "SECRET_KEY": secret_key,
        # SQLAlchemy
        "SQLALCHEMY_DATABASE_URI": database_uri,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True, "pool_recycle": 280},
        # JWT
        "JWT_SECRET_KEY": jwt_secret_key,
        "JWT_ACCESS_TOKEN_EXPIRES": timedelta(
            hours=int(os.environ.get("ZHY_JWT_ACCESS_HOURS", 2))
        ),
        "JWT_REFRESH_TOKEN_EXPIRES": timedelta(
            days=int(os.environ.get("ZHY_JWT_REFRESH_DAYS", 30))
        ),
        # CORS
        "CORS_ORIGINS": cors_origins,
        # Redis 缓存（可选；为空时降级为内存缓存）
        "REDIS_URL": redis_url,
        # 业务配置
        "STORAGE_DIR": storage_dir,
        "DEFAULT_QUOTA": default_quota,
        "MAX_UPLOAD_SIZE": max_upload,
        "MAX_CONTENT_LENGTH": max_upload,
        # 私有云盘默认不开放公开注册，管理员可在后台开启（DB 设置优先于此配置）
        "ALLOW_REGISTER": _env_bool(
            "ZHY_ALLOW_REGISTER", bool(installed.get("allow_register", False))
        ),
        "DENIED_EXTENSIONS": DENIED_EXTENSIONS,
        "CATEGORY_EXTENSIONS": CATEGORY_EXTENSIONS,
        # 插件
        "PLUGIN_DIRS": [
            str(BASE_DIR / "app" / "plugins" / "builtin"),
            str(BASE_DIR.parent / "plugins"),
        ],
        "JSON_AS_ASCII": False,
    }
