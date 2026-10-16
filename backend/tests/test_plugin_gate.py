"""M5：插件扩展路由网关——启用态拦截 + 登录态要求。

不动态注册蓝图（session app 首请求后禁止注册），而是直接在请求上下文中
执行 app.preprocess_request()，网关 before_request 链即被真实触发。
"""
import pytest

from app.plugins.base import BasePlugin
from app.plugins.manager import manager
from app.utils.errors import ApiError


class _AuthPlugin(BasePlugin):
    name = "gate-test-auth"
    supported_exts = ("txt",)


class _AnonPlugin(BasePlugin):
    name = "gate-test-anon"
    supported_exts = ("txt",)
    REQUIRE_AUTH = False


@pytest.fixture(autouse=True)
def _gate_plugins():
    manager._plugins["gate-test-auth"] = _AuthPlugin()
    manager._plugins["gate-test-anon"] = _AnonPlugin()
    yield
    manager._plugins.pop("gate-test-auth", None)
    manager._plugins.pop("gate-test-anon", None)


def _run_gate(app, path, headers=None):
    """执行网关链，返回 (http_status, biz_code 或 None 表示放行)。"""
    with app.test_request_context(path, headers=headers or {}):
        try:
            app.preprocess_request()
            return 200, None
        except ApiError as e:
            return e.http_status, e.code


def test_ext_requires_login_when_enabled(app):
    assert _run_gate(app, "/api/plugin/ext/gate-test-auth/ping") == (401, 4010)


def test_ext_accessible_with_valid_token(app, user_headers):
    assert _run_gate(
        app, "/api/plugin/ext/gate-test-auth/ping", headers=user_headers
    ) == (200, None)


def test_ext_rejects_invalid_token(app):
    status, code = _run_gate(
        app,
        "/api/plugin/ext/gate-test-auth/ping",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert status == 401


def test_ext_anonymous_plugin_open_without_token(app):
    """REQUIRE_AUTH=False 的插件允许匿名访问。"""
    assert _run_gate(
        app, "/api/plugin/ext/gate-test-anon/ping"
    ) == (200, None)


def test_ext_disabled_plugin_blocked(app, user_headers):
    """禁用（manager 不再持有实例）后，残留路由被网关 403。"""
    manager._plugins.pop("gate-test-auth", None)
    assert _run_gate(
        app, "/api/plugin/ext/gate-test-auth/ping", headers=user_headers
    ) == (403, 5102)


def test_ext_unknown_plugin_blocked(app, user_headers):
    assert _run_gate(
        app, "/api/plugin/ext/no-such-plugin/ping", headers=user_headers
    ) == (403, 5102)


def test_ext_illegal_name_blocked(app, user_headers):
    # 含大写/下划线等非法字符的插件名一律拒绝，不进入实例查找
    assert _run_gate(
        app, "/api/plugin/ext/Evil_X/ping", headers=user_headers
    ) == (403, 5102)
