"""插件测试：列表/启停/注册/可用查询/文件流/保存/权限校验。"""
import io

from tests.conftest import make_upload


def test_plugin_list(client, admin_headers):
    r = client.get("/api/plugin/list", headers=admin_headers)
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert len(data["items"]) >= 3
    names = [p["name"] for p in data["items"]]
    assert "image-preview" in names
    assert "video-preview" in names
    assert "document-preview" in names


def test_plugin_available_by_suffix(client, admin_headers, user_headers):
    r = client.get("/api/plugin/available?suffix=jpg", headers=user_headers)
    assert r.status_code == 200
    items = r.get_json()["data"]["items"]
    assert any(p["name"] == "image-preview" for p in items)


def test_plugin_available_unauthenticated(client):
    r = client.get("/api/plugin/available?suffix=jpg")
    assert r.status_code == 401


def test_plugin_enable_disable(client, admin_headers):
    # 禁用
    r = client.put("/api/plugin/image-preview/enabled", headers=admin_headers,
                   json={"enabled": False})
    assert r.status_code == 200
    assert r.get_json()["data"]["plugin"]["enabled"] is False
    # available 不再返回
    r = client.get("/api/plugin/available?suffix=jpg", headers=admin_headers)
    items = r.get_json()["data"]["items"]
    assert all(p["name"] != "image-preview" for p in items)
    # 重新启用
    r = client.put("/api/plugin/image-preview/enabled", headers=admin_headers,
                   json={"enabled": True})
    assert r.status_code == 200


def test_plugin_non_admin_blocked(client, user_headers):
    r = client.get("/api/plugin/list", headers=user_headers)
    assert r.status_code == 403


def test_plugin_file_stream_owner(client, user_headers):
    """归属用户通过插件 API 读取文件流。"""
    png = b"\x89PNG\r\n\x1a\n" + b"test" * 10
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(png), "img.png")})
    file_id = r.get_json()["data"]["success"][0]["id"]
    r = client.get(f"/api/plugin/file/stream?id={file_id}", headers=user_headers)
    assert r.status_code == 200
    assert r.data == png


def test_plugin_file_stream_share(client, user_headers):
    """分享访客通过 code+token 读取文件流。"""
    png = b"\x89PNG\r\n\x1a\n" + b"shared" * 5
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(png), "shared.png")})
    file_id = r.get_json()["data"]["success"][0]["id"]
    r = client.post("/api/share/create", headers=user_headers, json={"file_id": file_id})
    code = r.get_json()["data"]["share_code"]
    info = client.get(f"/api/share/info?code={code}").get_json()["data"]
    token = info["token"]
    r = client.get(f"/api/plugin/file/stream?code={code}&token={token}")
    assert r.status_code == 200
    assert r.data == png


def test_plugin_file_save(client, user_headers):
    """编辑保存回调：更新内容与文件大小。"""
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"original"), "edit.txt")})
    file_id = r.get_json()["data"]["success"][0]["id"]
    new_content = "edited content is longer than original"
    r = client.post("/api/plugin/file/save", headers=user_headers,
                    json={"id": file_id, "content": new_content})
    assert r.status_code == 200
    assert r.get_json()["data"]["file_size"] == len(new_content.encode())
    # 验证内容更新
    r = client.get(f"/api/plugin/file/stream?id={file_id}", headers=user_headers)
    assert r.data.decode() == new_content


def test_plugin_auth_check_owner(client, user_headers):
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"x"), "check.png")})
    file_id = r.get_json()["data"]["success"][0]["id"]
    r = client.get(f"/api/plugin/auth/check?id={file_id}", headers=user_headers)
    data = r.get_json()["data"]
    assert data["access"] == "owner"
    assert data["user"] == "testuser1"
    assert any(p["name"] == "image-preview" for p in data["plugins"])


def test_plugin_auth_check_share(client, user_headers):
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"y"), "shared2.png")})
    file_id = r.get_json()["data"]["success"][0]["id"]
    r = client.post("/api/share/create", headers=user_headers, json={"file_id": file_id})
    code = r.get_json()["data"]["share_code"]
    info = client.get(f"/api/share/info?code={code}").get_json()["data"]
    token = info["token"]
    r = client.get(f"/api/plugin/auth/check?code={code}&token={token}")
    data = r.get_json()["data"]
    assert data["access"] == "share"


def test_plugin_register_rescan(client, admin_headers):
    """重新扫描注册表。"""
    r = client.post("/api/plugin/register", headers=admin_headers, json={})
    assert r.status_code == 200
    assert "items" in r.get_json()["data"]
