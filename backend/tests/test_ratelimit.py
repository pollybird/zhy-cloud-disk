"""M1：登录/注册路由限频与连续失败临时锁定。"""
import pytest

from app.services import auth_service
from app.utils.errors import ApiError


# ---------------- 路由层限频 ----------------

def test_login_rate_limited_per_ip_account(client):
    # 前 5 次错误密码：正常返回 401（1103）
    for _ in range(5):
        r = client.post("/api/login", json={"username": "admin", "password": "bad"})
        assert r.status_code == 401
        assert r.get_json()["code"] == 1103
    # 第 6 次：同 IP+账号被限频，请求不进入密码校验
    r = client.post("/api/login", json={"username": "admin", "password": "bad"})
    assert r.status_code == 429
    assert r.get_json()["code"] == 4290


def test_login_rate_limit_isolated_by_account(client):
    """同 IP 不同账号各自计数：admin 被挡不影响其他账号尝试。"""
    for _ in range(5):
        client.post("/api/login", json={"username": "admin", "password": "bad"})
    r = client.post("/api/login", json={"username": "admin", "password": "bad"})
    assert r.get_json()["code"] == 4290
    # 另一账号仍可尝试（返回的是密码错误而非限频）
    r = client.post("/api/login", json={"username": "nobody", "password": "bad"})
    assert r.status_code == 401
    assert r.get_json()["code"] == 1103


def test_register_rate_limited_per_ip(client):
    for i in range(3):
        r = client.post("/api/register", json={
            "username": f"rluser{i}",
            "email": f"rluser{i}@test.com",
            "password": "Rg1234567",
        })
        assert r.status_code == 200
    # 第 4 次注册请求：同 IP 超限
    r = client.post("/api/register", json={
        "username": "rluserx",
        "email": "rluserx@test.com",
        "password": "Rg1234567",
    })
    assert r.status_code == 429
    assert r.get_json()["code"] == 4290


# ---------------- Service 层失败锁定 ----------------

def test_account_locked_after_10_failures(app):
    with app.test_request_context("/api/login", environ_base={"REMOTE_ADDR": "10.9.9.9"}):
        for _ in range(9):
            with pytest.raises(ApiError) as exc:
                auth_service.authenticate("admin", "bad")
            assert exc.value.code == 1103
        # 第 10 次失败：触发锁定
        with pytest.raises(ApiError) as exc:
            auth_service.authenticate("admin", "bad")
        assert exc.value.code == 4291
        # 锁定期内即使密码正确也拒绝
        with pytest.raises(ApiError) as exc:
            auth_service.authenticate("admin", "Admin12345")
        assert exc.value.code == 4291


def test_successful_login_clears_fail_counter(app):
    with app.test_request_context("/api/login", environ_base={"REMOTE_ADDR": "10.8.8.8"}):
        for _ in range(3):
            with pytest.raises(ApiError) as exc:
                auth_service.authenticate("admin", "bad")
            assert exc.value.code == 1103
        # 成功登录清空计数
        auth_service.authenticate("admin", "Admin12345")
        # 重新累计：再失败 9 次仍不触发锁定（计数从 0 开始）
        for _ in range(9):
            with pytest.raises(ApiError) as exc:
                auth_service.authenticate("admin", "bad")
            assert exc.value.code == 1103
