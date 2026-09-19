"""钟毓私有云盘 —— Flask 应用工厂。"""
from flask import Flask

from .config import ZHY_VERSION, build_config, _resolve_instance_dir
from .extensions import cors, db, jwt
from .services.setup_service import is_installed


def create_app(config_overrides: dict | None = None) -> Flask:
    """创建并配置 Flask 应用。

    未安装状态下应用以最小默认配置启动，仅放行安装向导相关接口；
    安装向导完成后通过 setup_service 在运行期内热切换数据库配置。
    """
    instance_dir = _resolve_instance_dir()
    app = Flask(__name__, instance_path=str(instance_dir))
    app.config.update(build_config())
    if config_overrides:
        app.config.update(config_overrides)

    instance_dir.mkdir(parents=True, exist_ok=True)

    # 初始化扩展
    db.init_app(app)
    jwt.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    # 初始化缓存（Redis 优先，降级内存）
    from .services.cache_service import init_cache

    init_cache(app)

    # 统一错误处理
    from .utils.errors import register_error_handlers

    register_error_handlers(app)

    # JWT 吊销列表：每次受保护请求检查 jti 是否已被吊销
    @jwt.token_in_blocklist_loader
    def _check_jti_revoked(jwt_header, jwt_data):
        from .services.cache_service import cache_exists

        jti = jwt_data.get("jti")
        if not jti:
            return False
        return cache_exists(f"jwt:revoked:{jti}")

    # 安装态全局拦截（必须在业务蓝图之前评估）
    _register_install_guard(app)

    # 健康检查
    @app.get("/api/ping")
    def ping():
        from .utils.response import success

        return success({"version": ZHY_VERSION, "installed": is_installed()})

    # 已安装：导入模型并建表（幂等），启动定时任务与插件系统。
    # 注意：功能开关必须在蓝图注册之前读取，部门蓝图按开关条件注册。
    if is_installed():
        _import_models()
        with app.app_context():
            db.create_all()
            from .utils.migrations import (
                ensure_department_columns,
                ensure_file_hash_column,
                ensure_v130_columns,
            )

            ensure_file_hash_column()
            ensure_department_columns()
            ensure_v130_columns()
        _start_scheduler(app)
        _init_plugins(app)

        # 1.1.0 功能开关：从系统设置读取是否开启部门共享网盘
        try:
            from .services.setting_service import get_raw

            with app.app_context():
                department_enabled = get_raw("department_drive_enabled") == "true"
            app.config["DEPARTMENT_DRIVE_ENABLED"] = department_enabled
        except Exception:
            app.logger.exception("读取部门功能开关失败，默认关闭")
            app.config["DEPARTMENT_DRIVE_ENABLED"] = False

    # 监控钩子无状态：未安装时无登录用户、业务请求被安装守卫拦截，自然空转，
    # 故无条件注册（兼容先建应用后执行安装向导的流程）。
    _register_metrics_hooks(app)

    # 注册蓝图
    from .api import register_blueprints

    register_blueprints(app)

    return app


def _register_install_guard(app: Flask) -> None:
    """未安装时拦截除安装向导、健康检查外的所有 /api 请求。"""
    from flask import request

    from .utils.errors import ApiError

    @app.before_request
    def _guard():
        if not request.path.startswith("/api/"):
            return None
        if is_installed():
            return None
        if request.path == "/api/ping" or request.path.startswith("/api/setup/"):
            return None
        raise ApiError("系统尚未安装，请先完成安装向导", code=4001, http_status=503)


def _register_metrics_hooks(app: Flask) -> None:
    """监控统计钩子：活跃用户心跳（60s 节流）与上传/下载流量累计。

    统计失败不得影响正常请求。
    """
    from flask import g, request

    _UPLOAD_PATHS = {"/api/file/upload", "/api/file/chunk/upload"}
    _DOWNLOAD_PATHS = {
        "/api/file/download",
        "/api/file/version/download",
        "/api/share/download",
    }

    @app.after_request
    def _collect_metrics(response):
        try:
            from .services import metrics_service

            user = getattr(g, "current_user", None)
            if user is not None:
                metrics_service.touch_active(user)

            if response.status_code == 200:
                if request.method == "POST" and request.path in _UPLOAD_PATHS:
                    length = request.content_length or 0
                    if length > 0:
                        metrics_service.record_traffic(up=length)
                elif request.method == "GET" and request.path in _DOWNLOAD_PATHS:
                    try:
                        length = int(response.headers.get("Content-Length") or 0)
                    except ValueError:
                        length = 0
                    if length > 0:
                        metrics_service.record_traffic(down=length)
        except Exception:
            app.logger.debug("监控指标采集失败", exc_info=True)
        return response


def _import_models() -> None:
    """导入全部模型以注册表到 SQLAlchemy 元数据。"""
    from .models import (  # noqa: F401
        backup_record,
        department,
        download_log,
        file_blob,
        file_lock,
        file_node,
        file_permission,
        file_version,
        operation_log,
        plugin,
        share,
        system_setting,
        trash_item,
        upload_session,
        user,
    )


def _start_scheduler(app: Flask) -> None:
    """启动 APScheduler 后台任务（第四阶段起生效）。"""
    try:
        from .tasks.scheduler import start_scheduler

        start_scheduler(app)
    except ImportError:
        # 阶段 0-3 调度器尚未实现
        pass


def _init_plugins(app: Flask) -> None:
    """发现并加载插件（第五阶段起生效；失败不阻断主进程）。"""
    try:
        from .plugins.manager import manager

        loaded = manager.discover_and_sync(app)
        app.logger.info("插件加载完成：%s", [p.name for p in loaded])
    except Exception:
        app.logger.exception("插件系统初始化失败（不影响核心功能）")
