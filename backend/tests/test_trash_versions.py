"""1.3.0：回收站与文件历史版本。

覆盖：软删保留/还原/彻底删除、同名重传、文件夹子树、过期清理、
回收站开关、版本归档/恢复/数量淘汰、版本开关、越权访问。
"""
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pytest

from app.extensions import db
from app.models.file_blob import FileBlob
from app.models.file_node import FileNode
from app.models.file_version import FileVersion
from app.models.trash_item import TrashItem
from app.models.user import User
from app.services import setting_service, trash_service


def _tag():
    return uuid.uuid4().hex[:8]


@pytest.fixture(autouse=True)
def _isolate_personal_data(app):
    """session 级共享库：每个用例前清空个人文件/回收站/版本并重置策略开关。

    各用例使用 uuid 前缀隔离文件名；此处直接清理行，历史 blob 行残留不影响
    以唯一 hash 为断言条件的用例。
    """
    with app.app_context():
        db.session.query(FileVersion).delete(synchronize_session=False)
        db.session.query(TrashItem).delete(synchronize_session=False)
        db.session.query(FileNode).filter(FileNode.department_id.is_(None)).delete(
            synchronize_session=False
        )
        db.session.query(User).filter(
            User.username.in_(["testuser1", "testuser2"])
        ).update({User.used_storage: 0}, synchronize_session=False)
        db.session.commit()
        setting_service.set_raw(setting_service.KEY_TRASH_ENABLED, "true")
        setting_service.set_raw(setting_service.KEY_VERSION_ENABLED, "true")
        setting_service.set_raw(setting_service.KEY_TRASH_RETENTION_DAYS, "30")
        setting_service.set_raw(setting_service.KEY_VERSION_MAX_COUNT, "10")
        setting_service.set_raw(setting_service.KEY_VERSION_RETENTION_DAYS, "30")


def upload_file(client, headers, name, content):
    return client.post(
        "/api/file/upload",
        data={"files": (BytesIO(content), name)},
        headers=headers,
        content_type="multipart/form-data",
    )


def overwrite(client, headers, node_id, name, content):
    return client.post(
        "/api/file/upload",
        data={
            "files": (BytesIO(content), name),
            "mode": "overwrite",
            "overwrite_id": str(node_id),
        },
        headers=headers,
        content_type="multipart/form-data",
    )


def _node_id(client, headers, name_key):
    r = client.get("/api/file/list", headers=headers)
    for item in r.get_json()["data"]["items"]:
        if item["file_name"].endswith(name_key):
            return item["id"]
    raise AssertionError(f"未找到文件 {name_key}")


def _used(app, username="testuser1"):
    with app.app_context():
        return db.session.query(User).filter_by(username=username).first().used_storage


def _blob_count(h):
    return db.session.query(FileBlob).filter_by(file_hash=h).count()


def _blob_ref(h):
    blob = db.session.query(FileBlob).filter_by(file_hash=h).first()
    return blob.ref_count if blob else None


def _update_settings(client, admin_headers, **kwargs):
    r = client.put("/api/admin/settings", json=kwargs, headers=admin_headers)
    assert r.status_code == 200, r.get_json()
    return r


# ---------------------------------------------------------------------------
# 回收站
# ---------------------------------------------------------------------------

def test_soft_delete_keeps_blob_quota_and_physical(app, client, user_headers):
    tag = _tag()
    content = f"trash-{tag}".encode() * 50
    import hashlib
    h = hashlib.md5(content).hexdigest()
    r = upload_file(client, user_headers, f"{tag}_a.txt", content)
    node_id = r.get_json()["data"]["success"][0]["id"]
    used_before = _used(app)

    assert client.delete("/api/file/delete", json={"id": node_id}, headers=user_headers).status_code == 200

    # 列表不可见
    assert _node_id_safe(client, user_headers, f"{tag}_a.txt") is None
    # 回收站可见
    trash = client.get("/api/file/trash", headers=user_headers).get_json()["data"]["items"]
    assert len(trash) == 1 and trash[0]["file_name"] == f"{tag}_a.txt"
    # 配额不变、blob 引用不变、物理文件保留
    assert _used(app) == used_before
    with app.app_context():
        assert _blob_ref(h) == 1
    root = Path(app.config["STORAGE_DIR"]) / "blobs"
    assert any(p.name == h for p in root.glob("*/*"))


def _node_id_safe(client, headers, suffix):
    r = client.get("/api/file/list", headers=headers)
    for item in r.get_json()["data"]["items"]:
        if item["file_name"] == suffix:
            return item["id"]
    return None


def test_restore_file_content_intact(app, client, user_headers):
    tag = _tag()
    content = f"restore-{tag}".encode() * 30
    node_id = upload_file(client, user_headers, f"{tag}_r.txt", content).get_json()["data"]["success"][0]["id"]
    client.delete("/api/file/delete", json={"id": node_id}, headers=user_headers)
    trash_id = client.get("/api/file/trash", headers=user_headers).get_json()["data"]["items"][0]["id"]

    r = client.post("/api/file/trash/restore", json={"id": trash_id}, headers=user_headers)
    assert r.status_code == 200
    restored_id = r.get_json()["data"]["id"]
    assert client.get(f"/api/file/download?id={restored_id}", headers=user_headers).data == content
    assert client.get("/api/file/trash", headers=user_headers).get_json()["data"]["items"] == []


def test_delete_then_reupload_same_name_and_restore_rename(app, client, user_headers):
    tag = _tag()
    name = f"{tag}_same.txt"
    content1 = f"old-{tag}".encode() * 10
    content2 = f"new-{tag}".encode() * 10
    id1 = upload_file(client, user_headers, name, content1).get_json()["data"]["success"][0]["id"]
    client.delete("/api/file/delete", json={"id": id1}, headers=user_headers)

    # 同名重传不撞唯一约束
    id2 = upload_file(client, user_headers, name, content2).get_json()["data"]["success"][0]["id"]
    assert id1 != id2
    assert client.get(f"/api/file/download?id={id2}", headers=user_headers).data == content2

    # 还原旧条目：同级冲突自动改名
    trash_id = client.get("/api/file/trash", headers=user_headers).get_json()["data"]["items"][0]["id"]
    r = client.post("/api/file/trash/restore", json={"id": trash_id}, headers=user_headers)
    assert r.status_code == 200
    assert r.get_json()["data"]["file_name"] == f"{tag}_same (1).txt"


def test_hard_delete_releases_everything(app, client, user_headers):
    import hashlib
    tag = _tag()
    content = f"hard-{tag}".encode() * 40
    h = hashlib.md5(content).hexdigest()
    node_id = upload_file(client, user_headers, f"{tag}_h.txt", content).get_json()["data"]["success"][0]["id"]
    assert _used(app) == len(content)

    client.delete("/api/file/delete", json={"id": node_id}, headers=user_headers)
    r = client.delete("/api/file/trash?scope=personal", headers=user_headers)
    assert r.get_json()["data"]["count"] == 1

    assert _used(app) == 0
    with app.app_context():
        assert _blob_count(h) == 0
    root = Path(app.config["STORAGE_DIR"]) / "blobs"
    assert not any(p.name == h for p in root.glob("*/*"))


def test_folder_soft_delete_and_restore(app, client, user_headers):
    tag = _tag()
    folder = f"{tag}_folder"
    r = client.post("/api/folder/create", json={"file_name": folder}, headers=user_headers)
    folder_id = r.get_json()["data"]["id"]
    content = f"infolder-{tag}".encode() * 20
    upload_file_in = client.post(
        "/api/file/upload",
        data={"files": (BytesIO(content), "x.txt"), "parent_id": str(folder_id)},
        headers=user_headers,
        content_type="multipart/form-data",
    )
    file_id = upload_file_in.get_json()["data"]["success"][0]["id"]

    client.delete("/api/file/delete", json={"id": folder_id}, headers=user_headers)
    assert _node_id_safe(client, user_headers, folder) is None

    trash_id = client.get("/api/file/trash", headers=user_headers).get_json()["data"]["items"][0]["id"]
    client.post("/api/file/trash/restore", json={"id": trash_id}, headers=user_headers)

    # 文件夹与内部文件均恢复
    assert _node_id_safe(client, user_headers, folder) is not None
    assert client.get(f"/api/file/download?id={file_id}", headers=user_headers).data == content


def test_expired_trash_purged(app, client, user_headers):
    import hashlib
    tag = _tag()
    content = f"exp-{tag}".encode() * 20
    h = hashlib.md5(content).hexdigest()
    node_id = upload_file(client, user_headers, f"{tag}_e.txt", content).get_json()["data"]["success"][0]["id"]
    client.delete("/api/file/delete", json={"id": node_id}, headers=user_headers)

    with app.app_context():
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        TrashItem.query.update({"expire_time": past})
        db.session.commit()
        result = trash_service.purge_expired()
        assert result["count"] == 1
        assert _blob_count(h) == 0


def test_trash_disabled_deletes_immediately(app, client, admin_headers, user_headers):
    import hashlib
    tag = _tag()
    content = f"nodisabled-{tag}".encode() * 20
    h = hashlib.md5(content).hexdigest()
    node_id = upload_file(client, user_headers, f"{tag}_d.txt", content).get_json()["data"]["success"][0]["id"]

    _update_settings(client, admin_headers, trash_enabled=False)
    client.delete("/api/file/delete", json={"id": node_id}, headers=user_headers)
    assert client.get("/api/file/trash", headers=user_headers).get_json()["data"]["items"] == []
    with app.app_context():
        assert _blob_count(h) == 0
    assert _used(app) == 0
    # 恢复默认
    _update_settings(client, admin_headers, trash_enabled=True)


def test_trash_cross_user_isolation(app, client, user_headers, user2_headers):
    tag = _tag()
    content = f"iso-{tag}".encode() * 10
    node_id = upload_file(client, user_headers, f"{tag}_iso.txt", content).get_json()["data"]["success"][0]["id"]
    client.delete("/api/file/delete", json={"id": node_id}, headers=user_headers)

    # user2 个人回收站看不到 user1 的条目
    assert client.get("/api/file/trash", headers=user2_headers).get_json()["data"]["items"] == []
    trash_id = client.get("/api/file/trash", headers=user_headers).get_json()["data"]["items"][0]["id"]
    r = client.post("/api/file/trash/restore", json={"id": trash_id}, headers=user2_headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 历史版本
# ---------------------------------------------------------------------------

def test_version_created_on_overwrite_and_restore(app, client, user_headers):
    tag = _tag()
    name = f"{tag}_v.txt"
    content_a = f"AAAA-{tag}".encode() * 30
    content_b = f"BBBB-{tag}".encode() * 30
    node_id = upload_file(client, user_headers, name, content_a).get_json()["data"]["success"][0]["id"]

    overwrite(client, user_headers, node_id, name, content_b)
    assert client.get(f"/api/file/download?id={node_id}", headers=user_headers).data == content_b

    versions = client.get(f"/api/file/versions/{node_id}", headers=user_headers).get_json()["data"]["items"]
    assert len(versions) == 1 and versions[0]["version_no"] == 1
    version_id = versions[0]["id"]

    # 下载旧版本
    r = client.get(f"/api/file/version/download?version_id={version_id}", headers=user_headers)
    assert r.data == content_a

    # 恢复：当前 B 归档为新版本，节点回到 A
    r = client.post("/api/file/version/restore", json={"version_id": version_id}, headers=user_headers)
    assert r.status_code == 200
    assert client.get(f"/api/file/download?id={node_id}", headers=user_headers).data == content_a
    versions2 = client.get(f"/api/file/versions/{node_id}", headers=user_headers).get_json()["data"]["items"]
    # v1 已成为当前（行删除），B 归档为 v2
    assert [v["version_no"] for v in versions2] == [2]


def test_version_count_pruning(app, client, admin_headers, user_headers):
    tag = _tag()
    name = f"{tag}_prune.txt"
    node_id = upload_file(client, user_headers, name, b"v0" * 10).get_json()["data"]["success"][0]["id"]
    _update_settings(client, admin_headers, version_max_count=2, version_retention_days=365)
    try:
        for i in range(1, 5):
            overwrite(client, user_headers, node_id, name, f"content-{i}-{tag}".encode() * 10)
        versions = client.get(f"/api/file/versions/{node_id}", headers=user_headers).get_json()["data"]["items"]
        assert len(versions) == 2
        assert [v["version_no"] for v in versions] == [4, 3]
    finally:
        _update_settings(client, admin_headers, version_max_count=10, version_retention_days=30)


def test_version_disabled_no_archive_and_restore_blocked(app, client, admin_headers, user_headers):
    import hashlib
    tag = _tag()
    name = f"{tag}_off.txt"
    content_a = f"oldver-{tag}".encode() * 20
    content_b = f"newver-{tag}".encode() * 20
    ha = hashlib.md5(content_a).hexdigest()
    node_id = upload_file(client, user_headers, name, content_a).get_json()["data"]["success"][0]["id"]

    _update_settings(client, admin_headers, version_enabled=False)
    overwrite(client, user_headers, node_id, name, content_b)
    versions = client.get(f"/api/file/versions/{node_id}", headers=user_headers).get_json()["data"]["items"]
    assert versions == []
    with app.app_context():
        # 旧 blob 已按 v1.2.0 逻辑释放
        assert _blob_count(ha) == 0

    # 重新开启并产生一个版本，再关闭 → restore 被拒绝
    _update_settings(client, admin_headers, version_enabled=True)
    overwrite(client, user_headers, node_id, name, content_a)
    version_id = client.get(f"/api/file/versions/{node_id}", headers=user_headers).get_json()["data"]["items"][0]["id"]
    _update_settings(client, admin_headers, version_enabled=False)
    r = client.post("/api/file/version/restore", json={"version_id": version_id}, headers=user_headers)
    assert r.status_code == 400 and r.get_json()["code"] == 3510
    _update_settings(client, admin_headers, version_enabled=True)


def test_versions_other_user_denied(app, client, user_headers, user2_headers):
    tag = _tag()
    name = f"{tag}_perm.txt"
    node_id = upload_file(client, user_headers, name, f"a-{tag}".encode() * 10).get_json()["data"]["success"][0]["id"]
    overwrite(client, user_headers, node_id, name, f"b-{tag}".encode() * 10)
    version_id = client.get(f"/api/file/versions/{node_id}", headers=user_headers).get_json()["data"]["items"][0]["id"]
    # 个人文件他人不可访问
    r = client.get(f"/api/file/version/download?version_id={version_id}", headers=user2_headers)
    assert r.status_code == 404
