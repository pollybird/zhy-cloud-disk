"""蓝图注册中心。"""

from flask import current_app, request

from ..utils.errors import ApiError

_DEPT_PREFIXES = ("/api/department", "/api/permission", "/api/log/")


def _dept_feature_guard():
    """部门功能开关检查：未开启时所有部门相关接口返回 4030。"""
    if not current_app.config.get("DEPARTMENT_DRIVE_ENABLED"):
        if request.path.startswith(_DEPT_PREFIXES):
            raise ApiError("部门网盘功能未开启", code=4030, http_status=403)


def register_department_blueprints(app) -> None:
    """幂等注册 1.1.0 部门共享相关蓝图。

    始终注册蓝图，功能开关通过 app 级 before_request 守卫在路由层检查。
    这避免了安装向导完成后热注册蓝图触发 Flask "setup finished" 断言错误。
    """
    if "department" in app.blueprints:
        return
    from .department import bp as dept_bp
    from .log import bp as log_bp
    from .permission import bp as perm_bp

    app.register_blueprint(dept_bp)
    app.register_blueprint(perm_bp)
    app.register_blueprint(log_bp)

    # 功能开关守卫（app 级，避免蓝图单例跨 app 复用冲突）
    app.before_request(_dept_feature_guard)


def register_blueprints(app) -> None:
    # 基础蓝图（始终注册）
    from .auth import bp as auth_bp
    from .file import bp as file_bp
    from .plugin import bp as plugin_bp
    from .setup import bp as setup_bp
    from .share import bp as share_bp
    from .system import bp as system_bp
    from .user import bp as user_bp

    app.register_blueprint(setup_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(file_bp)
    app.register_blueprint(share_bp)
    app.register_blueprint(plugin_bp)
    app.register_blueprint(system_bp)

    # 1.1.0 部门共享蓝图（始终注册，功能开关在路由层检查）
    register_department_blueprints(app)
