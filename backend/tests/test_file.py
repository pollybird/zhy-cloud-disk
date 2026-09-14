"""文件管理测试：上传、下载、列表、文件夹、重命名、移动、删除、配额。"""
import io

from tests.conftest import make_upload


def test_upload_success(client, user_headers):
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"hello world"), "test.txt")})
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert len(data["success"]) == 1
    assert data["success"][0]["file_name"] == "test.txt"
    assert data["success"][0]["file_size"] == 11


def test_upload_denied_extension(client, user_headers):
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"x"), "malicious.py")})
    data = r.get_json()["data"]
    assert len(data["failed"]) == 1
    assert "py" in data["failed"][0]["msg"]


def test_upload_to_folder(client, user_headers):
    # 建文件夹
    r = client.post("/api/folder/create", headers=user_headers, json={"file_name": "docs"})
    folder_id = r.get_json()["data"]["id"]
    # 上传到文件夹
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"in folder"), "doc.txt"), "parent_id": folder_id})
    assert r.status_code == 200
    assert len(r.get_json()["data"]["success"]) == 1
    # 列表应包含该文件
    r = client.get(f"/api/file/list?parent_id={folder_id}", headers=user_headers)
    assert r.get_json()["data"]["total"] == 1


def test_list_files(client, user_headers):
    client.post("/api/file/upload", headers=user_headers,
                data={"files": (io.BytesIO(b"a"), "a.txt")})
    client.post("/api/file/upload", headers=user_headers,
                data={"files": (io.BytesIO(b"bb"), "b.txt")})
    r = client.get("/api/file/list", headers=user_headers)
    assert r.status_code == 200
    assert r.get_json()["data"]["total"] >= 2


def test_list_with_pagination(client, user_headers):
    for i in range(5):
        client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"x"), f"page{i}.txt")})
    r = client.get("/api/file/list?page=1&size=2", headers=user_headers)
    assert r.get_json()["data"]["total"] >= 5
    assert len(r.get_json()["data"]["items"]) == 2


def test_download_success(client, user_headers):
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"download me"), "dl.txt")})
    file_id = r.get_json()["data"]["success"][0]["id"]
    r = client.get(f"/api/file/download?id={file_id}", headers=user_headers)
    assert r.status_code == 200
    assert r.data == b"download me"


def test_create_folder(client, user_headers):
    r = client.post("/api/folder/create", headers=user_headers, json={"file_name": "newfolder"})
    assert r.status_code == 200
    assert r.get_json()["data"]["is_folder"] is True


def test_create_folder_duplicate_name(client, user_headers):
    client.post("/api/folder/create", headers=user_headers, json={"file_name": "dup"})
    r = client.post("/api/folder/create", headers=user_headers, json={"file_name": "dup"})
    assert r.status_code == 409
    assert r.get_json()["code"] == 3103


def test_rename(client, user_headers):
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"x"), "old.txt")})
    file_id = r.get_json()["data"]["success"][0]["id"]
    r = client.put("/api/file/rename", headers=user_headers,
                   json={"id": file_id, "file_name": "new.txt"})
    assert r.status_code == 200
    assert r.get_json()["data"]["file_name"] == "new.txt"


def test_move_file(client, user_headers):
    # 建两个文件夹
    f1 = client.post("/api/folder/create", headers=user_headers, json={"file_name": "f1"})
    f2 = client.post("/api/folder/create", headers=user_headers, json={"file_name": "f2"})
    f1_id = f1.get_json()["data"]["id"]
    # 上传到 f1
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"x"), "movable.txt"), "parent_id": f1_id})
    file_id = r.get_json()["data"]["success"][0]["id"]
    # 移动到 f2
    f2_id = f2.get_json()["data"]["id"]
    r = client.put("/api/file/move", headers=user_headers,
                   json={"id": file_id, "target_parent_id": f2_id})
    assert r.status_code == 200
    assert r.get_json()["data"]["parent_id"] == f2_id


def test_move_to_self_subfolder_blocked(client, user_headers):
    # 建文件夹 parent 和子文件夹 child
    parent = client.post("/api/folder/create", headers=user_headers, json={"file_name": "parent"})
    parent_id = parent.get_json()["data"]["id"]
    child = client.post("/api/folder/create", headers=user_headers,
                        json={"file_name": "child", "parent_id": parent_id})
    child_id = child.get_json()["data"]["id"]
    # 尝试把 parent 移动到 child 内（形成环）
    r = client.put("/api/file/move", headers=user_headers,
                   json={"id": parent_id, "target_parent_id": child_id})
    assert r.status_code == 400
    assert r.get_json()["code"] == 3108


def test_delete_file(client, user_headers):
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"to delete"), "del.txt")})
    file_id = r.get_json()["data"]["success"][0]["id"]
    r = client.delete("/api/file/delete", headers=user_headers, json={"id": file_id})
    assert r.status_code == 200
    # 列表不再包含
    r = client.get("/api/file/list", headers=user_headers)
    items = r.get_json()["data"]["items"]
    assert all(i["id"] != file_id for i in items)


def test_delete_folder_recursive(client, user_headers):
    # 建文件夹 + 子文件
    folder = client.post("/api/folder/create", headers=user_headers, json={"file_name": "rfolder"})
    folder_id = folder.get_json()["data"]["id"]
    client.post("/api/file/upload", headers=user_headers,
                data={"files": (io.BytesIO(b"child"), "child.txt"), "parent_id": folder_id})
    # 删除文件夹
    r = client.delete("/api/file/delete", headers=user_headers, json={"id": folder_id})
    assert r.status_code == 200
    # 列表不含
    r = client.get("/api/file/list", headers=user_headers)
    items = r.get_json()["data"]["items"]
    assert all(i["id"] != folder_id for i in items)


def test_quota_enforcement(app, client):
    """配额拦截：给小配额用户上传超额文件。"""
    with app.app_context():
        from app.extensions import db
        from app.models.user import User
        from app.utils.security import hash_password

        user = User(
            username="quotauser", email="quota@test.com",
            password=hash_password("Quota12345"),
            role="user", status="active",
            total_storage=100, used_storage=0,
        )
        db.session.add(user)
        db.session.commit()

    r = client.post("/api/login", json={"username": "quotauser", "password": "Quota12345"})
    h = {"Authorization": f"Bearer {r.get_json()['data']['access_token']}"}

    # 上传 50B（成功）
    r = client.post("/api/file/upload", headers=h,
                    data={"files": (io.BytesIO(b"x" * 50), "small.txt")})
    assert len(r.get_json()["data"]["success"]) == 1

    # 再上传 60B（超额，因为 50+60>100）
    r = client.post("/api/file/upload", headers=h,
                    data={"files": (io.BytesIO(b"y" * 60), "big.txt")})
    data = r.get_json()["data"]
    assert len(data["failed"]) == 1


def test_category_filter(client, user_headers):
    client.post("/api/file/upload", headers=user_headers,
                data={"files": (io.BytesIO(b"x"), "photo.jpg")})
    client.post("/api/file/upload", headers=user_headers,
                data={"files": (io.BytesIO(b"y"), "note.txt")})
    r = client.get("/api/file/list?category=image", headers=user_headers)
    items = r.get_json()["data"]["items"]
    assert all(i["file_suffix"] == "jpg" for i in items)


def test_keyword_search(client, user_headers):
    client.post("/api/file/upload", headers=user_headers,
                data={"files": (io.BytesIO(b"x"), "special_report.pdf")})
    client.post("/api/file/upload", headers=user_headers,
                data={"files": (io.BytesIO(b"y"), "other.txt")})
    r = client.get("/api/file/list?keyword=special", headers=user_headers)
    items = r.get_json()["data"]["items"]
    assert any("special" in i["file_name"] for i in items)
    assert all("other" not in i["file_name"] for i in items)


def test_child_folders(client, user_headers):
    client.post("/api/folder/create", headers=user_headers, json={"file_name": "folderA"})
    client.post("/api/folder/create", headers=user_headers, json={"file_name": "folderB"})
    r = client.get("/api/file/folders", headers=user_headers)
    items = r.get_json()["data"]["items"]
    names = [i["file_name"] for i in items]
    assert "folderA" in names
    assert "folderB" in names


def test_upload_auto_rename_duplicate(client, user_headers):
    """同名文件自动追加 (1) 后缀。"""
    client.post("/api/file/upload", headers=user_headers,
                data={"files": (io.BytesIO(b"a"), "dup.txt")})
    r = client.post("/api/file/upload", headers=user_headers,
                    data={"files": (io.BytesIO(b"b"), "dup.txt")})
    name = r.get_json()["data"]["success"][0]["file_name"]
    assert "dup" in name and name != "dup.txt"
