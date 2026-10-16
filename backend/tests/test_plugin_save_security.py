"""H2：插件 /api/plugin/file/save 安全整改。

- 部门只读成员保存被拒（写权限校验）
- 他人持排他锁时保存冲突
- 共享内容块 copy-on-write：一个引用者保存不污染其他引用者
- 部门文件扣部门配额；超额拒绝、缩小回退；个人配额不被误扣
- 内容未变走短路，引用计数不变
"""
import json
from io import BytesIO

import pytest
from werkzeug.datastructures import FileStorage

from app import create_app
from app.extensions import db
from app.models.department import Department
from app.models.file_blob import FileBlob
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.services import (
    department_service,
    file_lock_service,
    file_service,
    permission_service,
)
from app.utils.security import hash_password


@pytest.fixture()
def app(tmp_path, monkeypatch):
    # 预写独立 installed 配置（强密钥），使 create_app 正常注册蓝图与建表
    inst = tmp_path / "instance"
    inst.mkdir()
    monkeypatch.setenv("ZHY_INSTANCE_DIR", str(inst))
    (inst / "config.installed.json").write_text(json.dumps({
        "secret_key": "h2-test-secret-key-0123456789abcdef",
        "jwt_secret_key": "h2-test-jwt-secret-0123456789abcdef0123456789",
        "database_uri": f"sqlite:///{tmp_path / 'test_h2.db'}",
    }))
    application = create_app({
        "DEPARTMENT_DRIVE_ENABLED": True,
        "STORAGE_DIR": str(tmp_path / "storage"),
        "TESTING": True,
    })
    with application.app_context():
        db.session.add(SystemSetting(key="department_drive_enabled", value="true"))
        db.session.commit()
        yield application


def _mk_user(name, email, role="user"):
    u = User(username=name, password=hash_password("Pass1234"),
             email=email, role=role, status="active")
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture()
def admin(app):
    return _mk_user("admin", "admin@test.com", role="admin")


@pytest.fixture()
def user_a(app):
    return _mk_user("h2a", "h2a@test.com")


@pytest.fixture()
def user_b(app):
    return _mk_user("h2b", "h2b@test.com")


@pytest.fixture()
def user_c(app):
    return _mk_user("h2c", "h2c@test.com")


@pytest.fixture()
def dept(admin, user_a, user_b, user_c):
    d = department_service.create_department("H2测试部", None, admin)
    for u in (user_a, user_b):
        department_service.add_member(d.id, u.id, "员工", admin)
        permission_service.grant_permission(u.id, d.id, None, "read_write", admin)
    # C 为默认只读成员
    department_service.add_member(d.id, user_c.id, "员工", admin)
    db.session.commit()
    return d


def _upload(operator, name, content, department_id=None):
    fs = FileStorage()
    fs.filename = name
    fs.stream = BytesIO(content)
    return file_service.upload_file(
        operator, fs, parent_id=None, department_id=department_id
    )


def _headers(client, name):
    r = client.post("/api/login", json={"username": name, "password": "Pass1234"})
    assert r.status_code == 200, r.get_json()
    return {"Authorization": f"Bearer {r.get_json()['data']['access_token']}"}


def _save(client, headers, node_id, content):
    return client.post(
        "/api/plugin/file/save",
        headers=headers,
        json={"id": node_id, "content": content},
    )


def _stream(client, headers, node_id):
    return client.get(f"/api/plugin/file/stream?id={node_id}", headers=headers)


# ---------------- H2-1 写权限与排他锁 ----------------

def test_readonly_member_cannot_save(client, dept, user_a, user_c):
    node = _upload(user_a, "note.txt", b"dept-file", department_id=dept.id)
    hc = _headers(client, "h2c")
    r = _save(client, hc, node.id, "hacked")
    assert r.status_code == 403
    assert r.get_json()["code"] == 4032
    # 内容未被修改
    ha = _headers(client, "h2a")
    assert _stream(client, ha, node.id).data == b"dept-file"


def test_save_blocked_by_other_user_lock(client, dept, user_a, user_b):
    node = _upload(user_a, "locked.txt", b"original-body", department_id=dept.id)
    # B 取得排他锁
    file_lock_service.acquire(user_b, node.id)
    ha = _headers(client, "h2a")
    r = _save(client, ha, node.id, "changed-by-a")
    assert r.status_code == 409
    assert r.get_json()["code"] == 3501
    # 锁持有者本人可保存
    hb = _headers(client, "h2b")
    r = _save(client, hb, node.id, "changed-by-b")
    assert r.status_code == 200
    assert _stream(client, hb, node.id).data == b"changed-by-b"


# ---------------- H2-3 共享 blob 不污染 ----------------

def test_shared_blob_save_does_not_pollute_other_refs(client, user_a):
    shared = b"SHARED-CONTENT" * 3
    node_a = _upload(user_a, "a.txt", shared)
    node_b = _upload(user_a, "b.txt", shared)

    # 去重：两节点引用同一 blob，计数 2
    assert node_a.save_path == node_b.save_path
    old_path = node_a.save_path
    old_hash = node_a.file_hash
    blob = db.session.query(FileBlob).filter(FileBlob.file_hash == old_hash).first()
    assert blob is not None and blob.ref_count == 2

    ha = _headers(client, "h2a")
    r = _save(client, ha, node_a.id, "brand new content for A only")
    assert r.status_code == 200

    db.session.refresh(node_a)
    db.session.refresh(node_b)
    # A 已切到新 blob；B 仍引用旧 blob
    assert node_a.save_path != old_path
    assert node_b.save_path == old_path
    assert node_b.file_hash == old_hash

    # 物理内容：B 完好，A 为新内容；旧 blob 物理块仍存在（B 在用）
    assert _stream(client, ha, node_b.id).data == shared
    new_data = _stream(client, ha, node_a.id).data
    assert new_data == b"brand new content for A only"

    import os
    assert os.path.exists(old_path)
    old_blob = db.session.query(FileBlob).filter(FileBlob.file_hash == old_hash).first()
    assert old_blob is not None and old_blob.ref_count == 1
    new_blob = db.session.query(FileBlob).filter(
        FileBlob.file_hash == node_a.file_hash
    ).first()
    assert new_blob is not None and new_blob.ref_count == 1


def test_save_then_other_ref_purged_removes_old_blob(client, user_a):
    """两个引用者之一改内容后，另一引用者被彻底删除，旧 blob 应归零物理删除。"""
    import hashlib
    import os

    from app.services import trash_service

    shared = b"to-be-diverged"
    node_a = _upload(user_a, "x.txt", shared)
    node_b = _upload(user_a, "y.txt", shared)
    old_path = node_a.save_path
    old_hash = hashlib.md5(shared).hexdigest()

    ha = _headers(client, "h2a")
    assert _save(client, ha, node_a.id, "A diverged").status_code == 200

    # B 彻底删除（回收站软删不释放 blob，直接 hard_delete 模拟清空回收站）
    db.session.refresh(node_b)
    trash_service.hard_delete(node_b, actor_id=user_a.id)

    old_blob = db.session.query(FileBlob).filter(
        FileBlob.file_hash == old_hash
    ).first()
    assert old_blob is None
    assert not os.path.exists(old_path)


# ---------------- H2-2 部门配额 ----------------

def test_department_quota_charged_and_refunded(client, dept, user_a):
    node = _upload(user_a, "q.txt", b"12345", department_id=dept.id)  # 5 字节
    d = db.session.get(Department, dept.id)
    assert d.used_storage == 5
    # 部门文件不计个人配额
    db.session.refresh(user_a)
    assert user_a.used_storage == 0

    # 设置刚好容纳当前用量的配额，增大保存被拒
    d.storage_quota = 5
    db.session.commit()
    ha = _headers(client, "h2a")
    r = _save(client, ha, node.id, "x" * 200)
    assert r.status_code == 413
    assert r.get_json()["code"] == 3106
    db.session.refresh(d)
    db.session.refresh(node)
    assert d.used_storage == 5
    assert node.file_size == 5

    # 放开配额后缩小保存：部门用量回退
    d.storage_quota = 0
    db.session.commit()
    r = _save(client, ha, node.id, "123")
    assert r.status_code == 200
    db.session.refresh(d)
    assert d.used_storage == 3
    db.session.refresh(user_a)
    assert user_a.used_storage == 0


# ---------------- 内容未变短路 ----------------

def test_save_identical_content_is_noop(client, user_a):
    content = "exact same text"
    node = _upload(user_a, "same.txt", content.encode())
    blob = db.session.query(FileBlob).filter(
        FileBlob.file_hash == node.file_hash
    ).first()
    assert blob.ref_count == 1

    ha = _headers(client, "h2a")
    r = _save(client, ha, node.id, content)
    assert r.status_code == 200
    db.session.refresh(blob)
    assert blob.ref_count == 1  # 未新增引用
    db.session.refresh(node)
    assert node.file_size == len(content.encode())
