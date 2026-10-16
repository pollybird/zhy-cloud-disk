"""M3：token_version 会话吊销机制与 refresh 一次性轮换。"""
import uuid

from flask_jwt_extended import decode_token


def _make_user(client):
    """注册独立随机用户并登录，返回 (uid, password, access_token, refresh_token)。"""
    uname = "mv" + uuid.uuid4().hex[:10]
    pwd = "Tv-Init-12345"
    r = client.post("/api/register", json={
        "username": uname,
        "email": f"{uname}@test.com",
        "password": pwd,
    })
    assert r.status_code == 200, r.get_json()
    r = client.post("/api/login", json={"username": uname, "password": pwd})
    assert r.status_code == 200
    data = r.get_json()["data"]
    return data["user"]["id"], pwd, data["access_token"], data["refresh_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_new_tokens_carry_tv_claim(client):
    _, _, access, refresh = _make_user(client)
    assert decode_token(access)["tv"] == 1
    assert decode_token(refresh)["tv"] == 1
    assert decode_token(refresh)["type"] == "refresh"


def test_change_password_revokes_old_tokens(client):
    _, pwd, access, refresh = _make_user(client)
    headers = _auth(access)
    assert client.get("/api/user/info", headers=headers).status_code == 200

    r = client.put("/api/user/pwd", headers=headers, json={
        "old_password": pwd,
        "new_password": "Tv-New-98765",
    })
    assert r.status_code == 200

    # 旧 access 立即失效（版本不匹配）
    r = client.get("/api/user/info", headers=headers)
    assert r.status_code == 401
    assert r.get_json()["code"] == 4015

    # 旧 refresh 同样失效，无法换取新令牌
    r = client.post("/api/auth/refresh", headers=_auth(refresh))
    assert r.status_code == 401
    assert r.get_json()["code"] == 4015


def test_refresh_token_is_single_use(client):
    _, _, _, refresh = _make_user(client)

    # 首次使用：换新令牌成功
    r = client.post("/api/auth/refresh", headers=_auth(refresh))
    assert r.status_code == 200
    new_pair = r.get_json()["data"]
    assert new_pair["access_token"]
    assert new_pair["refresh_token"] != refresh

    # 旧 refresh 重放：已被轮换吊销
    r = client.post("/api/auth/refresh", headers=_auth(refresh))
    assert r.status_code == 401
    assert r.get_json()["code"] == 4013

    # 轮换出的新 refresh 可继续使用（链式轮换）
    r = client.post("/api/auth/refresh", headers=_auth(new_pair["refresh_token"]))
    assert r.status_code == 200

    # 轮换出的新 access 可访问受保护接口
    r = client.get("/api/user/info", headers=_auth(new_pair["access_token"]))
    assert r.status_code == 200


def test_logout_access_does_not_revoke_refresh(client):
    """access/refresh 吊销列表分前缀：退出登录不影响 refresh 续期。"""
    _, _, access, refresh = _make_user(client)

    r = client.post("/api/logout", headers=_auth(access))
    assert r.status_code == 200
    assert client.get("/api/user/info", headers=_auth(access)).status_code == 401

    r = client.post("/api/auth/refresh", headers=_auth(refresh))
    assert r.status_code == 200
    new_access = r.get_json()["data"]["access_token"]
    assert client.get("/api/user/info", headers=_auth(new_access)).status_code == 200


def test_admin_disable_enable_revokes_sessions(client, admin_headers):
    uid, _, access, _ = _make_user(client)
    headers = _auth(access)
    assert client.get("/api/user/info", headers=headers).status_code == 200

    # 禁用：旧令牌被状态校验拦截
    r = client.put(
        f"/api/admin/users/{uid}/status",
        headers=admin_headers,
        json={"status": "disabled"},
    )
    assert r.status_code == 200
    r = client.get("/api/user/info", headers=headers)
    assert r.status_code == 403
    assert r.get_json()["code"] == 4031

    # 重新启用：禁用前的旧令牌仍不得复用（版本已递增）
    r = client.put(
        f"/api/admin/users/{uid}/status",
        headers=admin_headers,
        json={"status": "active"},
    )
    assert r.status_code == 200
    r = client.get("/api/user/info", headers=headers)
    assert r.status_code == 401
    assert r.get_json()["code"] == 4015


def test_admin_reset_password_revokes_sessions(client, admin_headers):
    uid, _, access, refresh = _make_user(client)
    headers = _auth(access)

    r = client.put(
        f"/api/admin/users/{uid}",
        headers=admin_headers,
        json={"new_password": "Tv-Reset-111"},
    )
    assert r.status_code == 200

    r = client.get("/api/user/info", headers=headers)
    assert r.status_code == 401
    assert r.get_json()["code"] == 4015

    r = client.post("/api/auth/refresh", headers=_auth(refresh))
    assert r.status_code == 401
    assert r.get_json()["code"] == 4015


def test_token_version_migration_idempotent(app):
    from app.extensions import db
    from app.utils.migrations import ensure_user_token_version
    from sqlalchemy import inspect

    with app.app_context():
        ensure_user_token_version()
        ensure_user_token_version()  # 重复执行不报错、不重复加列
        cols = {c["name"] for c in inspect(db.engine).get_columns("user")}
        assert "token_version" in cols
