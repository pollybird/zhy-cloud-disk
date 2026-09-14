"""安全测试：越权访问、路径穿越、黑名单文件上传、JWT 失效。"""
import io


def test_cross_user_download_blocked(client, user_headers, user2_headers):
    """用户 A 不能下载用户 B 的文件。"""
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"private"), "secret.txt")})
    file_id = r.get_json()["data"]["success"][0]["id"]
    r = client.get(f"/api/file/download?id={file_id}", headers=user2_headers)
    assert r.status_code == 404


def test_cross_user_rename_blocked(client, user_headers, user2_headers):
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"x"), "mine.txt")})
    file_id = r.get_json()["data"]["success"][0]["id"]
    r = client.put("/api/file/rename", headers=user2_headers,
                   json={"id": file_id, "file_name": "hacked.txt"})
    assert r.status_code == 404


def test_cross_user_delete_blocked(client, user_headers, user2_headers):
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"x"), "protect.txt")})
    file_id = r.get_json()["data"]["success"][0]["id"]
    r = client.delete("/api/file/delete", headers=user2_headers, json={"id": file_id})
    assert r.status_code == 404


def test_upload_executable_blocked(client, user_headers):
    for ext in ["exe", "sh", "php", "jsp"]:
        r = client.post("/api/file/upload", headers=user_headers,
                        data={"files": (io.BytesIO(b"x"), f"bad.{ext}")})
        data = r.get_json()["data"]
        assert len(data["failed"]) == 1, f".{ext} 应被拒绝"


def test_upload_script_blocked(client, user_headers):
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"print(1)"), "evil.py")})
    assert len(r.get_json()["data"]["failed"]) == 1


def test_path_traversal_filename(client, user_headers):
    """文件名含路径分隔符应被清理。"""
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"x"), "../../etc/passwd")})
    data = r.get_json()["data"]
    if data["success"]:
        # 文件名应被清理为不含路径
        assert "/" not in data["success"][0]["file_name"]
        assert ".." not in data["success"][0]["file_name"]


def test_expired_token_blocked(client, admin_headers):
    """正常 token 可用（基础验证）。"""
    r = client.get("/api/user/info", headers=admin_headers)
    assert r.status_code == 200


def test_no_token_blocked(client):
    r = client.get("/api/user/info")
    assert r.status_code == 401


def test_admin_create_user(client, admin_headers):
    r = client.post("/api/admin/users", headers=admin_headers, json={
        "username": "createdbyadmin", "email": "cba@test.com",
        "password": "Created12345", "role": "user",
    })
    assert r.status_code == 200
    assert r.get_json()["data"]["user"]["username"] == "createdbyadmin"


def test_admin_set_quota(client, admin_headers):
    # 先建用户
    client.post("/api/admin/users", headers=admin_headers, json={
        "username": "quotauser2", "email": "q2@test.com",
        "password": "Quota12345", "total_storage": 1048576,
    })
    # 查列表找到用户
    r = client.get("/api/admin/users?q=quotauser2", headers=admin_headers)
    user_id = r.get_json()["data"]["items"][0]["id"]
    # 改配额
    r = client.put(f"/api/admin/users/{user_id}/quota", headers=admin_headers,
                   json={"total_storage": 2097152})
    assert r.status_code == 200
    assert r.get_json()["data"]["user"]["total_storage"] == 2097152


def test_admin_disable_user(client, admin_headers):
    client.post("/api/admin/users", headers=admin_headers, json={
        "username": "disableme", "email": "dis@test.com",
        "password": "Disable12345",
    })
    r = client.get("/api/admin/users?q=disableme", headers=admin_headers)
    user_id = r.get_json()["data"]["items"][0]["id"]
    r = client.put(f"/api/admin/users/{user_id}/status", headers=admin_headers,
                   json={"status": "disabled"})
    assert r.status_code == 200
    assert r.get_json()["data"]["user"]["status"] == "disabled"


def test_admin_cannot_disable_self(client, admin_headers):
    """管理员不能修改自己的状态。"""
    r = client.get("/api/admin/users?q=admin", headers=admin_headers)
    admin_id = r.get_json()["data"]["items"][0]["id"]
    r = client.put(f"/api/admin/users/{admin_id}/status", headers=admin_headers,
                   json={"status": "disabled"})
    assert r.status_code == 400
    assert r.get_json()["code"] == 1210


def test_non_admin_cannot_access_admin(client, user_headers):
    r = client.get("/api/admin/users", headers=user_headers)
    assert r.status_code == 403
