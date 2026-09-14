"""分享测试：创建/信息/密码校验/下载/列表/取消/限频/过期。"""
import io

from tests.conftest import make_upload


def _upload_and_get_id(client, headers, name="share.txt", content=b"shareable"):
    r = client.post("/api/file/upload", headers=headers,
                    data={"files": (io.BytesIO(content), name)})
    return r.get_json()["data"]["success"][0]["id"]


def test_create_public_share(client, user_headers):
    file_id = _upload_and_get_id(client, user_headers)
    r = client.post("/api/share/create", headers=user_headers, json={
        "file_id": file_id, "expire_days": 0,
    })
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["share_code"]
    assert data["has_password"] is False
    assert data["status"] == "active"


def test_create_encrypted_share(client, user_headers):
    file_id = _upload_and_get_id(client, user_headers)
    r = client.post("/api/share/create", headers=user_headers, json={
        "file_id": file_id, "password": "Share12345", "expire_days": 7,
    })
    assert r.status_code == 200
    assert r.get_json()["data"]["has_password"] is True


def test_share_info_public(client, user_headers):
    file_id = _upload_and_get_id(client, user_headers)
    r = client.post("/api/share/create", headers=user_headers, json={
        "file_id": file_id, "expire_days": 0,
    })
    code = r.get_json()["data"]["share_code"]
    # info 返回令牌（公开分享）
    r = client.get(f"/api/share/info?code={code}")
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["token"] is not None
    assert data["need_password"] is False
    assert data["view_count"] >= 1


def test_share_info_encrypted(client, user_headers):
    file_id = _upload_and_get_id(client, user_headers)
    r = client.post("/api/share/create", headers=user_headers, json={
        "file_id": file_id, "password": "Share12345",
    })
    code = r.get_json()["data"]["share_code"]
    r = client.get(f"/api/share/info?code={code}")
    data = r.get_json()["data"]
    assert data["need_password"] is True
    assert data["token"] is None


def test_share_verify_password_success(client, user_headers):
    file_id = _upload_and_get_id(client, user_headers)
    r = client.post("/api/share/create", headers=user_headers, json={
        "file_id": file_id, "password": "Share12345",
    })
    code = r.get_json()["data"]["share_code"]
    r = client.post("/api/share/verify-password", json={"code": code, "password": "Share12345"})
    assert r.status_code == 200
    assert r.get_json()["data"]["token"] is not None


def test_share_verify_password_wrong(client, user_headers):
    file_id = _upload_and_get_id(client, user_headers)
    r = client.post("/api/share/create", headers=user_headers, json={
        "file_id": file_id, "password": "Share12345",
    })
    code = r.get_json()["data"]["share_code"]
    r = client.post("/api/share/verify-password", json={"code": code, "password": "wrong"})
    assert r.status_code == 403
    assert r.get_json()["code"] == 4105


def test_share_download_public(client, user_headers):
    file_id = _upload_and_get_id(client, user_headers, content=b"download me")
    r = client.post("/api/share/create", headers=user_headers, json={
        "file_id": file_id, "expire_days": 0,
    })
    code = r.get_json()["data"]["share_code"]
    info = client.get(f"/api/share/info?code={code}").get_json()["data"]
    token = info["token"]
    r = client.get(f"/api/share/download?code={code}&token={token}")
    assert r.status_code == 200
    assert r.data == b"download me"


def test_share_download_no_token_blocked(client, user_headers):
    file_id = _upload_and_get_id(client, user_headers)
    r = client.post("/api/share/create", headers=user_headers, json={
        "file_id": file_id, "expire_days": 0,
    })
    code = r.get_json()["data"]["share_code"]
    r = client.get(f"/api/share/download?code={code}")
    assert r.status_code == 403
    assert r.get_json()["code"] == 4104


def test_share_list(client, user_headers):
    file_id = _upload_and_get_id(client, user_headers)
    client.post("/api/share/create", headers=user_headers, json={"file_id": file_id})
    r = client.get("/api/share/list", headers=user_headers)
    assert r.status_code == 200
    assert r.get_json()["data"]["total"] >= 1


def test_share_cancel(client, user_headers):
    file_id = _upload_and_get_id(client, user_headers)
    r = client.post("/api/share/create", headers=user_headers, json={"file_id": file_id})
    share_id = r.get_json()["data"]["id"]
    r = client.delete("/api/share/cancel?id=" + str(share_id), headers=user_headers)
    assert r.status_code == 200
    # 再访问应被拒
    code = client.get("/api/share/list", headers=user_headers).get_json()["data"]["items"][0]["share_code"]
    r = client.get(f"/api/share/info?code={code}")
    assert r.status_code == 403
    assert r.get_json()["code"] == 4103


def test_share_rate_limit(client, user_headers):
    """密码限频：超过 5 次后返回 429。"""
    file_id = _upload_and_get_id(client, user_headers)
    r = client.post("/api/share/create", headers=user_headers, json={
        "file_id": file_id, "password": "Share12345",
    })
    code = r.get_json()["data"]["share_code"]
    for i in range(5):
        r = client.post("/api/share/verify-password", json={"code": code, "password": "wrong"})
        assert r.status_code == 403
    r = client.post("/api/share/verify-password", json={"code": code, "password": "wrong"})
    assert r.status_code == 429
    assert r.get_json()["code"] == 4106


def test_share_invalid_code(client):
    r = client.get("/api/share/info?code=nonexistent")
    assert r.status_code == 404
    assert r.get_json()["code"] == 4101


def test_share_create_nonexistent_file(client, user_headers):
    r = client.post("/api/share/create", headers=user_headers, json={"file_id": 99999})
    assert r.status_code == 404
    assert r.get_json()["code"] == 4101


def test_share_create_not_owner(client, user_headers, user2_headers):
    """越权创建他人文件的分享。"""
    file_id = _upload_and_get_id(client, user_headers)
    r = client.post("/api/share/create", headers=user2_headers, json={"file_id": file_id})
    assert r.status_code == 404
