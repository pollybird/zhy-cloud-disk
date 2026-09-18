"""1.2.0 部门文件排他编辑锁测试。

覆盖：
- 获取/续约/释放/状态查询与权限要求
- 他人持锁时覆盖、改名、移动、删除被拒；持有者本人放行
- 列表 locked/locked_by_me/lock_user_name 标注
- 过期锁自动失效；管理员强制释放
- 删除含锁定文件的文件夹被拒
- 个人文件不支持加锁
"""
from datetime import timedelta
from io import BytesIO

import pytest

from app import create_app
from app.extensions import db
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.services import (
    department_service,
    file_lock_service,
    file_service,
    permission_service,
)
from app.utils.errors import ApiError
from app.utils.security import hash_password


@pytest.fixture
def app(tmp_path):
    application = create_app({
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/test_lock.db",
        "DEPARTMENT_DRIVE_ENABLED": True,
        "STORAGE_DIR": str(tmp_path / "storage"),
        "TESTING": True,
    })
    with application.app_context():
        db.create_all()
        db.session.add(SystemSetting(key="department_drive_enabled", value="true"))
        db.session.commit()
        yield application


@pytest.fixture
def admin(app):
    u = User(username="admin", password=hash_password("Admin12345"),
             email="admin@test.com", role="admin", status="active")
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def user_a(app):
    return _mk_user("lockA", "a@test.com")


@pytest.fixture
def user_b(app):
    return _mk_user("lockB", "b@test.com")


@pytest.fixture
def user_c(app):
    return _mk_user("lockC", "c@test.com")


def _mk_user(name, email):
    u = User(username=name, password=hash_password("Pass1234"),
             email=email, role="user", status="active")
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def dept(admin, user_a, user_b, user_c):
    d = department_service.create_department("锁测试部", None, admin)
    for u in (user_a, user_b):
        department_service.add_member(d.id, u.id, "员工", admin)
        permission_service.grant_permission(u.id, d.id, None, "read_write", admin)
    # C 为默认只读成员
    department_service.add_member(d.id, user_c.id, "员工", admin)
    db.session.commit()
    return d


def _upload(operator, name, content=b"hello-lock", department_id=None, parent_id=None):
    from werkzeug.datastructures import FileStorage

    fs = FileStorage()
    fs.filename = name
    fs.stream = BytesIO(content)
    return file_service.upload_file(
        operator, fs, parent_id=parent_id, department_id=department_id
    )


def _overwrite(operator, node, content=b"new-content"):
    from werkzeug.datastructures import FileStorage

    fs = FileStorage()
    fs.filename = node.file_name
    fs.stream = BytesIO(content)
    return file_service.upload_file(
        operator, fs, parent_id=node.parent_id,
        mode="overwrite", overwrite_id=node.id,
        department_id=node.department_id,
    )


class TestAcquireRelease:
    def test_second_user_acquire_conflict(self, app, admin, dept, user_a, user_b):
        node = _upload(user_a, "方案.docx", department_id=dept.id)
        r = file_lock_service.acquire(user_a, node.id)
        assert r["held_by_me"] is True

        with pytest.raises(ApiError) as ei:
            file_lock_service.acquire(user_b, node.id)
        assert ei.value.code == 3501
        assert ei.value.data["user_name"] == "lockA"

    def test_holder_reacquire_is_idempotent_renew(self, app, admin, dept, user_a):
        node = _upload(user_a, "a.txt", department_id=dept.id)
        r1 = file_lock_service.acquire(user_a, node.id)
        r2 = file_lock_service.acquire(user_a, node.id)
        assert r1["lock"]["node_id"] == r2["lock"]["node_id"]
        st = file_lock_service.status(user_a, node.id)
        assert st["locked"] is True and st["held_by_me"] is True

    def test_heartbeat_and_release(self, app, admin, dept, user_a, user_b):
        node = _upload(user_a, "b.txt", department_id=dept.id)
        file_lock_service.acquire(user_a, node.id)
        # 非持有者心跳被拒
        with pytest.raises(ApiError) as ei:
            file_lock_service.renew(user_b, node.id)
        assert ei.value.code == 3501
        file_lock_service.renew(user_a, node.id)

        # 非持有者不能释放
        with pytest.raises(ApiError):
            file_lock_service.release(user_b, node.id)
        file_lock_service.release(user_a, node.id)
        assert file_lock_service.status(user_b, node.id)["locked"] is False
        # 释放后 B 可获取
        r = file_lock_service.acquire(user_b, node.id)
        assert r["held_by_me"] is True

    def test_read_only_user_cannot_lock(self, app, admin, dept, user_a, user_c):
        node = _upload(user_a, "c.txt", department_id=dept.id)
        with pytest.raises(ApiError) as ei:
            file_lock_service.acquire(user_c, node.id)
        assert ei.value.code == 4032

    def test_personal_file_not_lockable(self, app, admin, user_a):
        node = _upload(user_a, "p.txt")
        with pytest.raises(ApiError) as ei:
            file_lock_service.acquire(user_a, node.id)
        assert ei.value.code == 3503

    def test_expired_lock_taken_over(self, app, admin, dept, user_a, user_b):
        from datetime import datetime, timezone

        from app.models.file_lock import FileLock

        node = _upload(user_a, "d.txt", department_id=dept.id)
        file_lock_service.acquire(user_a, node.id)
        # 模拟 A 客户端崩溃：锁过期
        lock = db.session.get(FileLock, node.id)
        lock.expire_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.commit()

        r = file_lock_service.acquire(user_b, node.id)
        assert r["held_by_me"] is True
        assert r["lock"]["user_name"] == "lockB"

    def test_admin_force_release(self, app, admin, dept, user_a, user_b):
        node = _upload(user_a, "e.txt", department_id=dept.id)
        file_lock_service.acquire(user_a, node.id)
        # 普通成员不能强制释放
        with pytest.raises(ApiError):
            file_lock_service.release(user_b, node.id, force=True)
        # 超管可以
        file_lock_service.release(admin, node.id, force=True)
        assert file_lock_service.status(user_a, node.id)["locked"] is False


class TestWriteGuards:
    def test_other_user_blocked_overwrite_rename_delete(self, app, admin, dept, user_a, user_b):
        node = _upload(user_a, "报告.docx", b"v1", department_id=dept.id)
        file_lock_service.acquire(user_a, node.id)

        with pytest.raises(ApiError) as ei:
            _overwrite(user_b, node)
        assert ei.value.code == 3501
        with pytest.raises(ApiError):
            file_service.rename_node(user_b, node.id, "改名.docx")
        with pytest.raises(ApiError):
            file_service.delete_node(user_b, node.id)

    def test_holder_can_save_overwrite(self, app, admin, dept, user_a):
        node = _upload(user_a, "报告2.docx", b"v1", department_id=dept.id)
        file_lock_service.acquire(user_a, node.id)
        updated = _overwrite(user_a, node, b"v2-edited")
        assert updated.id == node.id and updated.file_size == len(b"v2-edited")
        # 保存后锁仍在（由客户端显式 release）
        assert file_lock_service.status(user_a, node.id)["locked"] is True

    def test_move_blocked_while_locked(self, app, admin, dept, user_a, user_b):
        folder = file_service.create_folder(user_a, None, "目录", dept.id)
        node = _upload(user_a, "m.txt", department_id=dept.id)
        file_lock_service.acquire(user_a, node.id)
        with pytest.raises(ApiError) as ei:
            file_service.move_node(user_b, node.id, folder.id)
        assert ei.value.code == 3501

    def test_delete_folder_with_locked_descendant_blocked(self, app, admin, dept, user_a):
        folder = file_service.create_folder(user_a, None, "项目", dept.id)
        inner = _upload(user_a, "x.docx", b"x", department_id=dept.id, parent_id=folder.id)
        file_lock_service.acquire(user_a, inner.id)
        # 即使是持有者本人，删除整个文件夹也被拒，避免连带删掉正在编辑的文件
        with pytest.raises(ApiError) as ei:
            file_service.delete_node(user_a, folder.id)
        assert ei.value.code == 3501


class TestListEnrichment:
    def test_list_carries_lock_fields(self, app, admin, dept, user_a, user_b, user_c):
        node = _upload(user_a, "共享.xlsx", b"123", department_id=dept.id)
        file_lock_service.acquire(user_a, node.id)

        view_a = file_service.list_files(user_a, department_id=dept.id)
        item_a = next(i for i in view_a["items"] if i["id"] == node.id)
        assert item_a["locked"] is True
        assert item_a["locked_by_me"] is True
        assert item_a["lock_user_name"] == "lockA"

        view_b = file_service.list_files(user_b, department_id=dept.id)
        item_b = next(i for i in view_b["items"] if i["id"] == node.id)
        assert item_b["locked"] is True
        assert item_b["locked_by_me"] is False
        assert item_b["lock_user_name"] == "lockA"

    def test_list_unlocked_fields_false(self, app, admin, dept, user_a):
        _upload(user_a, "自由.docx", b"1", department_id=dept.id)
        view = file_service.list_files(user_a, department_id=dept.id)
        item = view["items"][0]
        assert item["locked"] is False
        assert item["locked_by_me"] is False
        assert item["lock_user_name"] is None
