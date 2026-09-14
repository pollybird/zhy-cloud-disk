"""蓝图注册中心。"""


def register_blueprints(app) -> None:
    from .auth import bp as auth_bp
    from .file import bp as file_bp
    from .plugin import bp as plugin_bp
    from .setup import bp as setup_bp
    from .share import bp as share_bp
    from .user import bp as user_bp

    app.register_blueprint(setup_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(file_bp)
    app.register_blueprint(share_bp)
    app.register_blueprint(plugin_bp)
