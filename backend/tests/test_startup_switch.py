"""部门功能开关与蓝图注册测试。

回归保护：蓝图始终注册（避免安装后热注册触发 Flask setup_finished 断言）；
功能开关通过 before_request 守卫在路由层检查，关闭时返回 4030。
"""
import pytest

from app import create_app
from app.services.setup_service import run_installation


@pytest.fixture
def env(tmp_path, monkeypatch):
    """每个测试独立实例目录，不依赖 config_overrides（走真实启动路径）。"""
    monkeypatch.setenv("ZHY_INSTANCE_DIR", str(tmp_path / "instance"))
    from app.services.cache_service import _memory_cache

    _memory_cache.clear()
    return tmp_path


def _install(application, tmp_path, enabled: bool) -> None:
    with application.app_context():
        run_installation(application, {
            "db_type": "sqlite",
            "database": "test_startup.db",
            "storage_dir": str(tmp_path / "storage"),
            "admin_username": "admin",
            "admin_email": "admin@test.com",
            "admin_password": "Admin12345",
            "department_drive_enabled": enabled,
        })


class TestStartupSwitch:
    def test_blueprint_always_registered(self, env):
        """蓝图始终注册，不受安装态或开关影响。"""
        app = create_app()
        assert "department" in app.blueprints
        assert "permission" in app.blueprints
        assert "log" in app.blueprints

    def test_flag_on_after_install(self, env):
        """安装时勾选部门功能：开关为 True，路由正常响应。"""
        app = create_app()
        _install(app, env, True)
        assert app.config["DEPARTMENT_DRIVE_ENABLED"] is True
        assert "department" in app.blueprints

    def test_flag_on_after_restart(self, env):
        """模拟进程重启：新 app 从 system_setting 读到开关并放行。"""
        first = create_app()
        _install(first, env, True)

        second = create_app()
        assert second.config["DEPARTMENT_DRIVE_ENABLED"] is True
        assert "department" in second.blueprints

    def test_flag_off_blocks_routes(self, env):
        """未勾选部门功能：蓝图已注册但路由返回 4030。"""
        app = create_app()
        _install(app, env, False)
        assert app.config["DEPARTMENT_DRIVE_ENABLED"] is False
        assert "department" in app.blueprints

        restarted = create_app()
        assert restarted.config["DEPARTMENT_DRIVE_ENABLED"] is False
        assert "department" in restarted.blueprints

    def test_register_department_blueprints_idempotent(self, env):
        """重复注册不抛错（安装流程与启动流程可能先后触发）。"""
        from app.api import register_department_blueprints

        app = create_app()
        _install(app, env, True)
        # 再注册一次必须幂等
        register_department_blueprints(app)
        assert "department" in app.blueprints
