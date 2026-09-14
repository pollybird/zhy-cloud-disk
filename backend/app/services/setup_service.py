"""首次运行安装向导：安装状态检测、数据库测试、配置落盘、建库建超管。

安装态以 ``instance/config.installed.json`` 为唯一凭据；文件存在即视为已安装，
安装接口随即永久锁定。安装过程中该文件最后写入（原子 rename），
任何前置步骤失败都会回滚运行期状态与 SQLite 半成品文件。
"""
import fcntl
import json
import os
import platform
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from ..config import (
    DEFAULT_STORAGE_DIR,
    ZHY_VERSION,
    _resolve_installed_config_path,
    _resolve_instance_dir,
)
from ..extensions import db
from ..utils.errors import ApiError
from ..utils.security import generate_token, hash_password
from ..utils.validators import (
    DB_TYPES,
    validate_email,
    validate_password,
    validate_username,
)

# 进程内安装锁（文件锁跨进程/跨 worker 兜底）
_install_lock = threading.Lock()

_WRITE_PROBE_SQL = {
    "sqlite": "CREATE TEMP TABLE _zhy_write_probe (id INTEGER PRIMARY KEY)",
    "mysql": "CREATE TEMPORARY TABLE _zhy_write_probe (id INT PRIMARY KEY)",
    "postgresql": "CREATE TEMP TABLE _zhy_write_probe (id INT PRIMARY KEY)",
}


def is_installed() -> bool:
    return _resolve_installed_config_path().is_file()


def read_installed_config() -> dict:
    path = _resolve_installed_config_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
# 环境检测
# ---------------------------------------------------------------------------

def _dir_writable(path: Path, create: bool = True) -> bool:
    try:
        if create:
            path.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            return False
        probe = path / ".zhy_write_probe"
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def get_environment_info(storage_dir: str | None = None) -> dict:
    storage_target = Path(storage_dir) if storage_dir else DEFAULT_STORAGE_DIR
    try:
        inst_dir = _resolve_instance_dir()
        disk = shutil.disk_usage(inst_dir if inst_dir.exists() else Path.cwd())
        disk_free = disk.free
    except OSError:
        disk_free = None
    return {
        "app_version": ZHY_VERSION,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "instance_dir": str(_resolve_instance_dir()),
        "instance_writable": _dir_writable(_resolve_instance_dir()),
        "storage_dir": str(storage_target),
        "storage_writable": _dir_writable(storage_target),
        "disk_free": disk_free,
    }


# ---------------------------------------------------------------------------
# 数据库连接
# ---------------------------------------------------------------------------

def build_database_uri(payload: dict) -> tuple[str, str, Path | None]:
    """根据向导输入构造 SQLAlchemy URI。

    返回 (uri, db_type, sqlite_path)；非 sqlite 时第三项为 None。
    """
    db_type = (payload.get("db_type") or "sqlite").strip().lower()
    if db_type not in DB_TYPES:
        raise ApiError("不支持的数据库类型", code=2001)

    if db_type == "sqlite":
        name = (payload.get("database") or "zhycloud.db").strip()
        if not name:
            name = "zhycloud.db"
        if "/" in name or ".." in name or name.startswith("."):
            raise ApiError("SQLite 文件名不合法", code=2002)
        if not name.endswith(".db"):
            name += ".db"
        path = _resolve_instance_dir() / name
        return f"sqlite:///{path.as_posix()}", "sqlite", path

    host = (payload.get("host") or "").strip()
    database = (payload.get("database") or "").strip()
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not host or not database or not username:
        raise ApiError("请完整填写数据库主机、库名和账号", code=2003)
    try:
        port = int(payload.get("port") or (3306 if db_type == "mysql" else 5432))
    except (TypeError, ValueError):
        raise ApiError("数据库端口不合法", code=2004)

    auth = quote_plus(username)
    if password:
        auth += f":{quote_plus(str(password))}"
    if db_type == "mysql":
        uri = (
            f"mysql+pymysql://{auth}@{host}:{port}/{database}"
            "?charset=utf8mb4&connect_timeout=8"
        )
    else:
        uri = f"postgresql+psycopg2://{auth}@{host}:{port}/{database}?connect_timeout=8"
    return uri, db_type, None


def _db_type_of_uri(uri: str) -> str:
    if uri.startswith("sqlite"):
        return "sqlite"
    if uri.startswith("mysql"):
        return "mysql"
    if uri.startswith("postgresql"):
        return "postgresql"
    raise ApiError(f"无法识别的数据库连接串：{uri.split(':', 1)[0]}", code=2005)


def test_database(db_type: str, uri: str) -> None:
    """真实建立连接，并执行临时表写操作验证账号权限。"""
    if db_type not in _WRITE_PROBE_SQL:
        raise ApiError("不支持的数据库类型", code=2001)
    engine = None
    try:
        engine = create_engine(uri)
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                conn.execute(text("SELECT 1"))
                conn.execute(text(_WRITE_PROBE_SQL[db_type]))
            finally:
                trans.rollback()
    except ModuleNotFoundError as e:
        raise ApiError(f"数据库驱动缺失：{e.name}，请联系管理员安装", code=2006)
    except SQLAlchemyError as e:
        message = str(e.__dict__.get("orig", e))
        # 去掉可能的连接串/密码回显
        message = message.replace("\n", " ").strip()[:300]
        raise ApiError(f"数据库连接或写权限校验失败：{message}", code=2007)
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"数据库连接失败：{str(e)[:200]}", code=2007)
    finally:
        if engine is not None:
            engine.dispose()


# ---------------------------------------------------------------------------
# 安装执行
# ---------------------------------------------------------------------------

def _write_installed_config(cfg: dict) -> None:
    inst_dir = _resolve_instance_dir()
    config_path = _resolve_installed_config_path()
    inst_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(inst_dir), prefix=".config.installed.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, config_path)
        os.chmod(config_path, 0o600)
    except OSError as e:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise ApiError(f"安装配置写入失败：{e}", code=2010)


def _switch_engine(app, uri: str) -> None:
    """热切换运行期数据库引擎。

    Flask-SQLAlchemy 在 init_app 时按配置创建引擎并缓存在
    ``_app_engines``，且不允许二次 init_app；因此手动 dispose
    旧引擎并复用其内部方法按新 URI 重建默认引擎。
    """
    app.config["SQLALCHEMY_DATABASE_URI"] = uri
    engines = db._app_engines.setdefault(app, {})
    for old in list(engines.values()):
        try:
            old.dispose()
        except Exception:  # noqa: BLE001
            pass
    engines.clear()

    options = dict(db._engine_options)
    options.update(app.config.get("SQLALCHEMY_ENGINE_OPTIONS") or {})
    options["url"] = uri
    db._apply_driver_defaults(options, app)
    engines[None] = db._make_engine(None, options, app)


def run_installation(app, payload: dict) -> dict:
    """执行完整安装流程；成功返回超管信息。"""
    lock_path = _resolve_instance_dir() / "setup.lock"
    _resolve_instance_dir().mkdir(parents=True, exist_ok=True)
    # current_app 是 LocalProxy，WeakKeyDictionary 键必须是真实 Flask 对象
    app = getattr(app, "_get_current_object", lambda: app)()
    lock_file = open(lock_path, "a", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        with _install_lock:
            if is_installed():
                raise ApiError("系统已安装，安装向导已锁定", code=2020, http_status=403)
            return _do_install(app, payload)
    finally:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        lock_file.close()


def _do_install(app, payload: dict) -> dict:
    # 1. 校验超管信息
    admin_username = validate_username(payload.get("admin_username", ""))
    admin_email = validate_email(payload.get("admin_email", ""))
    admin_password = validate_password(payload.get("admin_password", ""))

    # 2. 构造并复测数据库（支持直连 DSN 透传，用于环境变量静默安装）
    direct_uri = payload.get("database_uri")
    if direct_uri:
        uri = direct_uri
        db_type = _db_type_of_uri(uri)
        sqlite_path = _resolve_instance_dir() / Path(uri.replace("sqlite:///", "")).name if db_type == "sqlite" else None
    else:
        uri, db_type, sqlite_path = build_database_uri(payload)
    test_database(db_type, uri)
    sqlite_pre_existed = bool(sqlite_path and sqlite_path.exists())

    # 3. 校验存储目录
    storage_dir = (payload.get("storage_dir") or app.config["STORAGE_DIR"]).strip()
    storage_path = Path(storage_dir).expanduser().resolve()
    if not _dir_writable(storage_path):
        raise ApiError(f"存储目录不可写：{storage_path}", code=2008)

    # 4. 准备落盘配置（密码不落盘）
    redis_url = (payload.get("redis_url") or "").strip()
    if not redis_url:
        redis_url = os.environ.get("ZHY_REDIS_URL", "")
    cfg = {
        "version": ZHY_VERSION,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "db_type": db_type,
        "database_uri": uri,
        "storage_dir": str(storage_path),
        "secret_key": generate_token(32),
        "jwt_secret_key": generate_token(48),
        "default_quota": int(app.config["DEFAULT_QUOTA"]),
        "max_upload_size": int(app.config["MAX_UPLOAD_SIZE"]),
        "allow_register": bool(app.config["ALLOW_REGISTER"]),
        "redis_url": redis_url,
    }

    # 5. 临时切换引擎 → 建表 → 建超管；最后才写安装标记
    old_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    marker_written = False
    try:
        _switch_engine(app, uri)
        # 确保模型已注册
        from ..models import (  # noqa: F401
            download_log,
            file_node,
            share,
            system_setting,
            user,
        )

        with app.app_context():
            db.create_all()
            if db.session.query(user.User).count() > 0:
                raise ApiError("目标数据库已存在用户数据，拒绝覆盖安装", code=2009)
            admin = user.User(
                username=admin_username,
                password=hash_password(admin_password),
                email=admin_email,
                role="admin",
                status="active",
                total_storage=int(app.config["DEFAULT_QUOTA"]),
                used_storage=0,
            )
            db.session.add(admin)
            db.session.commit()

            # 6. 写安装标记（原子落盘，安装完成点）
            _write_installed_config(cfg)
            marker_written = True

            app.config["SECRET_KEY"] = cfg["secret_key"]
            app.config["JWT_SECRET_KEY"] = cfg["jwt_secret_key"]
            app.config["STORAGE_DIR"] = str(storage_path)
            app.config["REDIS_URL"] = cfg.get("redis_url", "")
            # 安装后重新初始化缓存（此时 Redis URL 可能已变化）
            from .cache_service import init_cache

            init_cache(app)
    except Exception:
        db.session.rollback()
        # 回滚运行期引擎，保证向导可再次使用
        try:
            _switch_engine(app, old_uri)
        except Exception:  # noqa: BLE001
            app.logger.exception("回滚数据库引擎失败")
        if db_type == "sqlite" and not sqlite_pre_existed and sqlite_path and sqlite_path.exists():
            try:
                sqlite_path.unlink()
            except OSError:
                pass
        if marker_written:
            # 极端情况：标记已写但后续失败，移除标记交给人工处理
            try:
                _resolve_installed_config_path().unlink()
            except OSError:
                pass
        raise

    # 7. 安装完成后立即初始化插件系统（失败不影响安装结果）
    try:
        from ..plugins.manager import manager

        manager.discover_and_sync(app)
    except Exception:  # noqa: BLE001
        app.logger.exception("安装后插件初始化失败")

    return {
        "admin_username": admin_username,
        "admin_email": admin_email,
        "db_type": db_type,
        "storage_dir": str(storage_path),
        "installed_at": cfg["installed_at"],
    }


# ---------------------------------------------------------------------------
# Docker / 环境变量静默安装
# ---------------------------------------------------------------------------

def maybe_auto_install(app) -> bool:
    """环境变量齐全且系统未安装时，执行静默初始化。返回是否执行了安装。"""
    if is_installed():
        return False
    username = os.environ.get("ZHY_ADMIN_USERNAME")
    password = os.environ.get("ZHY_ADMIN_PASSWORD")
    if not username or not password:
        return False

    if os.environ.get("ZHY_DATABASE_URL"):
        uri = os.environ["ZHY_DATABASE_URL"]
        db_type = _db_type_of_uri(uri)
        payload = {"db_type": db_type, "database_uri": uri}
        if db_type == "sqlite" and os.environ.get("ZHY_SQLITE_NAME"):
            payload["database"] = os.environ["ZHY_SQLITE_NAME"]
    else:
        payload = {
            "db_type": os.environ.get("ZHY_DB_TYPE", "sqlite"),
            "host": os.environ.get("ZHY_DB_HOST", "127.0.0.1"),
            "port": os.environ.get("ZHY_DB_PORT", ""),
            "database": os.environ.get("ZHY_DB_NAME", "zhycloud"),
            "username": os.environ.get("ZHY_DB_USER", ""),
            "password": os.environ.get("ZHY_DB_PASSWORD", ""),
        }

    payload["admin_username"] = username
    payload["admin_password"] = password
    payload["admin_email"] = (
        os.environ.get("ZHY_ADMIN_EMAIL") or f"{username}@admin.local"
    )
    if os.environ.get("ZHY_STORAGE_DIR"):
        payload["storage_dir"] = os.environ["ZHY_STORAGE_DIR"]

    run_installation(app, payload)
    app.logger.info("环境变量静默安装完成，超级管理员：%s", username)
    return True
