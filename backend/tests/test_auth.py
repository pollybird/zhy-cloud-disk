"""认证测试：注册、登录、JWT 流程、退出吊销、令牌刷新。"""
import pytest


def test_login_success(client):
    r = client.post("/api/login", json={"username": "admin", "password": "Admin12345"})
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user"]["username"] == "admin"


def test_login_wrong_password(client):
    r = client.post("/api/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    assert r.get_json()["code"] == 1103


def test_login_missing_fields(client):
    r = client.post("/api/login", json={"username": "", "password": ""})
    assert r.status_code == 400
    assert r.get_json()["code"] == 1102


def test_register_success(client):
    r = client.post("/api/register", json={
        "username": "newuser1", "email": "new1@test.com", "password": "New12345",
    })
    assert r.status_code == 200
    assert r.get_json()["data"]["user"]["username"] == "newuser1"


def test_register_duplicate(client):
    client.post("/api/register", json={
        "username": "dupuser", "email": "dup@test.com", "password": "Dup12345",
    })
    r = client.post("/api/register", json={
        "username": "dupuser", "email": "other@test.com", "password": "Dup12345",
    })
    assert r.status_code == 409
    assert r.get_json()["code"] == 1101


def test_register_weak_password(client):
    r = client.post("/api/register", json={
        "username": "weakuser", "email": "weak@test.com", "password": "abc",
    })
    assert r.status_code == 400
    assert r.get_json()["code"] == 1003


def test_register_status_endpoint(client):
    r = client.get("/api/auth/register-status")
    assert r.status_code == 200
    assert "allow_register" in r.get_json()["data"]


def test_jwt_protected_endpoint(client):
    r = client.get("/api/user/info")
    assert r.status_code == 401
    assert r.get_json()["code"] == 4010


def test_user_info(client, admin_headers):
    r = client.get("/api/user/info", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()["data"]["user"]["username"] == "admin"


def test_logout_revokes_token(client, admin_headers):
    r = client.post("/api/logout", headers=admin_headers)
    assert r.status_code == 200
    # 旧 token 应被吊销
    r = client.get("/api/user/info", headers=admin_headers)
    assert r.status_code == 401
    assert r.get_json()["code"] == 4013


def test_refresh_token(client, admin_refresh):
    r = client.post("/api/auth/refresh", headers={"Authorization": f"Bearer {admin_refresh}"})
    assert r.status_code == 200
    assert r.get_json()["data"]["access_token"]


def test_change_password(client, admin_headers):
    r = client.put("/api/user/pwd", headers=admin_headers, json={
        "old_password": "Admin12345", "new_password": "NewPass12345",
    })
    assert r.status_code == 200
    # 新密码可登录
    r = client.post("/api/login", json={"username": "admin", "password": "NewPass12345"})
    assert r.status_code == 200
    # 旧密码失败
    r = client.post("/api/login", json={"username": "admin", "password": "Admin12345"})
    assert r.status_code == 401
    # 恢复
    client.put("/api/user/pwd", headers=admin_headers, json={
        "old_password": "NewPass12345", "new_password": "Admin12345",
    })


def test_change_password_wrong_old(client, admin_headers):
    r = client.put("/api/user/pwd", headers=admin_headers, json={
        "old_password": "wrong", "new_password": "NewPass12345",
    })
    assert r.status_code == 400
    assert r.get_json()["code"] == 1201
