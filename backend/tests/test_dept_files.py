"""阶段 6：部门文件浏览的权限感知测试。

覆盖：
- effective_department_permission / effective_node_permission 有效权限判定
- 部门树 my_permission 标注与显式授权可见性
- list_files 部门列表的 access 标注（部门级 + 文件夹级授权）
- list_child_folders 部门移动目录树（仅可写目标）
- move_node 个人空间 ↔ 部门网盘跨域移动防护
"""
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest

from app import create_app
from app.extensions import db
from app.models.department import Department, DepartmentMember
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.services import department_service, file_service, permission_service
from app.utils.errors import ApiError
from app.utils.security import hash_password


@pytest.fixture
def app(tmp_path):
    application = create_app({
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/test_dept_files.db",
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
    user = User(
        username="admin",
        password=hash_password("Admin12345"),
        email="admin@test.com",
        role="admin",
        status="active",
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def user_a(app):
    user = User(
        username="userA",
        password=hash_password("Pass1234"),
        email="a@test.com",
        role="user",
        status="active",
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def user_b(app):
    user = User(
        username="userB",
        password=hash_password("Pass1234"),
        email="b@test.com",
        role="user",
        status="active",
    )
    db.session.add(user)
    db.session.commit()
    return user


def _make_dept(admin, name="技术部", parent_id=None, quota=1024 * 1024):
    dept = department_service.create_department(name, parent_id, admin)
    dept.storage_quota = quota
    db.session.commit()
    return dept


def _upload(operator, filename, content, department_id=None, parent_id=None):
    from werkzeug.datastructures import FileStorage

    fs = FileStorage()
    fs.filename = filename
    fs.stream = BytesIO(content)
    return file_service.upload_file(
        operator, fs, parent_id=parent_id, department_id=department_id
    )


# ---------------------------------------------------------------------------
# 有效权限判定
# ---------------------------------------------------------------------------

class TestEffectivePermission:
    def test_super_admin_always_write(self, app, admin):
        dept = _make_dept(admin)
        assert permission_service.effective_department_permission(admin, dept.id) == "read_write"

    def test_member_default_read_only(self, app, admin, user_a):
        dept = _make_dept(admin)
        department_service.add_member(dept.id, user_a.id, "员工", admin)
        assert permission_service.effective_department_permission(user_a, dept.id) == "read_only"
        assert permission_service.check_department_access(user_a, dept.id, "read") is True
        assert permission_service.check_department_access(user_a, dept.id, "write") is False

    def test_explicit_read_write(self, app, admin, user_a):
        dept = _make_dept(admin)
        permission_service.grant_permission(user_a.id, dept.id, None, "read_write", admin)
        assert permission_service.effective_department_permission(user_a, dept.id) == "read_write"

    def test_explicit_read_only_for_non_member(self, app, admin, user_a):
        dept = _make_dept(admin)
        permission_service.grant_permission(user_a.id, dept.id, None, "read_only", admin)
        assert permission_service.effective_department_permission(user_a, dept.id) == "read_only"

    def test_denied_member_gets_none(self, app, admin, user_a):
        dept = _make_dept(admin)
        department_service.add_member(dept.id, user_a.id, "员工", admin)
        permission_service.grant_permission(user_a.id, dept.id, None, "denied", admin)
        assert permission_service.effective_department_permission(user_a, dept.id) == "none"
        assert permission_service.check_department_access(user_a, dept.id, "read") is False

    def test_outsider_none(self, app, admin, user_a):
        dept = _make_dept(admin)
        assert permission_service.effective_department_permission(user_a, dept.id) == "none"

    def test_expired_grant_falls_back_to_member(self, app, admin, user_a):
        dept = _make_dept(admin)
        department_service.add_member(dept.id, user_a.id, "员工", admin)
        past = datetime.now(timezone.utc) - timedelta(days=1)
        permission_service.grant_permission(
            user_a.id, dept.id, None, "read_write", admin, expire_time=past
        )
        assert permission_service.effective_department_permission(user_a, dept.id) == "read_only"

    def test_folder_level_grant_rw_for_member(self, app, admin, user_a):
        """成员默认只读，对某文件夹授权读写后，文件夹内节点可写、根目录仍只读。"""
        dept = _make_dept(admin)
        department_service.add_member(dept.id, user_a.id, "员工", admin)
        folder = file_service.create_folder(admin, None, "共享项目", department_id=dept.id)
        permission_service.grant_permission(
            user_a.id, dept.id, folder.id, "read_write", admin
        )
        inner_file = _upload(admin, "a.txt", b"a", department_id=dept.id, parent_id=folder.id)
        root_file = _upload(admin, "root.txt", b"r", department_id=dept.id)

        assert permission_service.effective_node_permission(user_a, folder) == "read_write"
        assert permission_service.effective_node_permission(user_a, inner_file) == "read_write"
        assert permission_service.effective_node_permission(user_a, root_file) == "read_only"

    def test_folder_level_denied_blocks_inner_file(self, app, admin, user_a):
        dept = _make_dept(admin)
        department_service.add_member(dept.id, user_a.id, "员工", admin)
        folder = file_service.create_folder(admin, None, "机密", department_id=dept.id)
        permission_service.grant_permission(
            user_a.id, dept.id, folder.id, "denied", admin
        )
        inner_file = _upload(admin, "secret.txt", b"s", department_id=dept.id, parent_id=folder.id)
        assert permission_service.effective_node_permission(user_a, inner_file) == "none"
        assert permission_service.check_file_access(user_a, inner_file, "read") is False

    def test_personal_node_owner_only(self, app, admin, user_a):
        node = _upload(admin, "mine.txt", b"m")
        assert permission_service.effective_node_permission(admin, node) == "read_write"
        # 超管对个人文件也可访问
        assert permission_service.effective_node_permission(admin, node) == "read_write"
        other = _upload(user_a, "other.txt", b"o")
        assert permission_service.effective_node_permission(admin, other) == "read_write"
        assert permission_service.effective_node_permission(user_a, node) == "none"


# ---------------------------------------------------------------------------
# 部门树权限标注
# ---------------------------------------------------------------------------

class TestDepartmentTreeAnnotation:
    def test_admin_tree_all_write(self, app, admin):
        root = _make_dept(admin, "总公司")
        sub = _make_dept(admin, "技术部", parent_id=root.id)
        tree = department_service.get_department_tree(admin)
        assert tree[0]["my_permission"] == "read_write"
        assert tree[0]["children"][0]["id"] == sub.id
        assert tree[0]["children"][0]["my_permission"] == "read_write"

    def test_member_tree_read_only(self, app, admin, user_a):
        dept = _make_dept(admin)
        department_service.add_member(dept.id, user_a.id, "员工", admin)
        tree = department_service.get_department_tree(user_a)
        assert tree[0]["id"] == dept.id
        assert tree[0]["my_permission"] == "read_only"

    def test_non_member_with_ro_grant_visible(self, app, admin, user_a):
        dept = _make_dept(admin)
        permission_service.grant_permission(user_a.id, dept.id, None, "read_only", admin)
        tree = department_service.get_department_tree(user_a)
        assert len(tree) == 1
        assert tree[0]["my_permission"] == "read_only"

    def test_denied_only_non_member_hidden(self, app, admin, user_a):
        """非成员仅被 denied 授权时，部门树不暴露该部门。"""
        dept = _make_dept(admin)
        permission_service.grant_permission(user_a.id, dept.id, None, "denied", admin)
        assert department_service.get_department_tree(user_a) == []

    def test_member_denied_visible_but_none(self, app, admin, user_a):
        dept = _make_dept(admin)
        department_service.add_member(dept.id, user_a.id, "员工", admin)
        permission_service.grant_permission(user_a.id, dept.id, None, "denied", admin)
        tree = department_service.get_department_tree(user_a)
        assert tree[0]["my_permission"] == "none"

    def test_outsider_tree_empty(self, app, admin, user_a):
        _make_dept(admin)
        assert department_service.get_department_tree(user_a) == []


# ---------------------------------------------------------------------------
# 部门文件列表 access 标注
# ---------------------------------------------------------------------------

class TestDepartmentListAccess:
    def test_root_list_annotation_for_member(self, app, admin, user_a):
        dept = _make_dept(admin)
        department_service.add_member(dept.id, user_a.id, "员工", admin)
        folder = file_service.create_folder(admin, None, "项目A", department_id=dept.id)
        permission_service.grant_permission(
            user_a.id, dept.id, folder.id, "read_write", admin
        )
        _upload(admin, "root.txt", b"r", department_id=dept.id)
        _upload(admin, "a.txt", b"a", department_id=dept.id, parent_id=folder.id)

        result = file_service.list_files(user_a, None, dept.id)
        # 成员对部门根目录默认只读
        assert result["access"] == "read_only"
        perms = {item["file_name"]: item["access"] for item in result["items"]}
        assert perms["root.txt"] == "read_only"
        assert perms["项目A"] == "read_write"

    def test_list_into_granted_folder(self, app, admin, user_a):
        dept = _make_dept(admin)
        department_service.add_member(dept.id, user_a.id, "员工", admin)
        folder = file_service.create_folder(admin, None, "项目A", department_id=dept.id)
        permission_service.grant_permission(
            user_a.id, dept.id, folder.id, "read_write", admin
        )
        _upload(admin, "a.txt", b"a", department_id=dept.id, parent_id=folder.id)

        result = file_service.list_files(user_a, folder.id, dept.id)
        assert result["access"] == "read_write"
        assert result["items"][0]["access"] == "read_write"

    def test_rw_member_root_writable(self, app, admin, user_a):
        dept = _make_dept(admin)
        permission_service.grant_permission(user_a.id, dept.id, None, "read_write", admin)
        _upload(admin, "root.txt", b"r", department_id=dept.id)
        result = file_service.list_files(user_a, None, dept.id)
        assert result["access"] == "read_write"
        assert result["items"][0]["access"] == "read_write"

    def test_outsider_list_denied(self, app, admin, user_a):
        dept = _make_dept(admin)
        with pytest.raises(ApiError, match="无权访问该部门文件"):
            file_service.list_files(user_a, None, dept.id)

    def test_personal_list_has_no_access_field(self, app, admin):
        """1.0.0 兼容：个人文件响应不携带 access 字段。"""
        _upload(admin, "mine.txt", b"m")
        result = file_service.list_files(admin, None, None)
        assert "access" not in result
        assert "access" not in result["items"][0]


# ---------------------------------------------------------------------------
# 部门移动目录树
# ---------------------------------------------------------------------------

class TestDepartmentChildFolders:
    def test_read_only_member_root_forbidden(self, app, admin, user_a):
        dept = _make_dept(admin)
        department_service.add_member(dept.id, user_a.id, "员工", admin)
        file_service.create_folder(admin, None, "F1", department_id=dept.id)
        with pytest.raises(ApiError, match="无权在该部门移动文件"):
            file_service.list_child_folders(user_a, None, dept.id)

    def test_rw_member_lists_root_folders(self, app, admin, user_a):
        dept = _make_dept(admin)
        permission_service.grant_permission(user_a.id, dept.id, None, "read_write", admin)
        file_service.create_folder(admin, None, "F1", department_id=dept.id)
        file_service.create_folder(admin, None, "F2", department_id=dept.id)
        names = {f["file_name"] for f in file_service.list_child_folders(user_a, None, dept.id)}
        assert names == {"F1", "F2"}

    def test_folder_level_rw_can_expand(self, app, admin, user_a):
        dept = _make_dept(admin)
        department_service.add_member(dept.id, user_a.id, "员工", admin)
        f1 = file_service.create_folder(admin, None, "F1", department_id=dept.id)
        file_service.create_folder(admin, f1.id, "Sub", department_id=dept.id)
        permission_service.grant_permission(user_a.id, dept.id, f1.id, "read_write", admin)
        items = file_service.list_child_folders(user_a, f1.id, dept.id)
        assert [i["file_name"] for i in items] == ["Sub"]

    def test_denied_folder_excluded(self, app, admin, user_b):
        dept = _make_dept(admin)
        permission_service.grant_permission(user_b.id, dept.id, None, "read_write", admin)
        f1 = file_service.create_folder(admin, None, "F1", department_id=dept.id)
        f2 = file_service.create_folder(admin, None, "F2", department_id=dept.id)
        permission_service.grant_permission(user_b.id, dept.id, f2.id, "denied", admin)
        names = {f["file_name"] for f in file_service.list_child_folders(user_b, None, dept.id)}
        # 根目录可展开（部门级 rw），但 F2 被禁止、F1 继承部门 rw
        assert names == {"F1"}

    def test_personal_folders_unchanged(self, app, admin):
        file_service.create_folder(admin, None, "个人目录")
        items = file_service.list_child_folders(admin, None, None)
        assert [i["file_name"] for i in items] == ["个人目录"]


# ---------------------------------------------------------------------------
# 跨域移动防护
# ---------------------------------------------------------------------------

class TestCrossBoundaryMove:
    def test_dept_file_into_personal_folder_rejected(self, app, admin):
        dept = _make_dept(admin)
        personal_folder = file_service.create_folder(admin, None, "个人目录")
        dept_file = _upload(admin, "d.txt", b"d", department_id=dept.id)
        with pytest.raises(ApiError, match="不能在个人空间与部门网盘之间移动文件"):
            file_service.move_node(admin, dept_file.id, personal_folder.id)

    def test_personal_file_into_dept_folder_rejected(self, app, admin):
        dept = _make_dept(admin)
        dept_folder = file_service.create_folder(
            admin, None, "部门目录", department_id=dept.id
        )
        personal_file = _upload(admin, "p.txt", b"p")
        with pytest.raises(ApiError, match="不能在个人空间与部门网盘之间移动文件"):
            file_service.move_node(admin, personal_file.id, dept_folder.id)

    def test_move_within_same_department_ok(self, app, admin):
        dept = _make_dept(admin)
        f1 = file_service.create_folder(admin, None, "F1", department_id=dept.id)
        f2 = file_service.create_folder(admin, None, "F2", department_id=dept.id)
        node = _upload(admin, "d.txt", b"d", department_id=dept.id, parent_id=f1.id)
        moved = file_service.move_node(admin, node.id, f2.id)
        assert moved.parent_id == f2.id
        assert moved.department_id == dept.id

    def test_move_dept_file_to_dept_root_ok(self, app, admin):
        dept = _make_dept(admin)
        f1 = file_service.create_folder(admin, None, "F1", department_id=dept.id)
        node = _upload(admin, "d.txt", b"d", department_id=dept.id, parent_id=f1.id)
        moved = file_service.move_node(admin, node.id, None)
        assert moved.parent_id is None
        assert moved.department_id == dept.id
