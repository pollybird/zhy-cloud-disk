"""部门与权限服务单元测试。

覆盖：
- 部门 CRUD（无限级树、同级不重名、迁移防环）
- 成员管理（添加/移除/更新）
- 管理员委派（scope=self/self_and_sub、分级权限边界）
- 权限检查（denied 最高优先级、read_write、read_only、默认成员权限）
- 部门文件上传与配额
"""
import io

import pytest

from app import create_app
from app.extensions import db
from app.models.department import Department, DepartmentAdmin, DepartmentMember
from app.models.file_node import FileNode
from app.models.file_permission import FilePermission
from app.models.user import User
from app.services import department_service, file_service, permission_service
from app.utils.errors import ApiError


@pytest.fixture
def app(tmp_path):
    """创建带部门功能开启的测试应用。"""
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/test_dept.db",
        "DEPARTMENT_DRIVE_ENABLED": True,
        "STORAGE_DIR": str(tmp_path / "storage"),
        "TESTING": True,
    })
    with app.app_context():
        db.create_all()
        # 写入功能开关
        from app.models.system_setting import SystemSetting
        db.session.add(SystemSetting(key="department_drive_enabled", value="true"))
        db.session.commit()
        yield app


@pytest.fixture
def admin(app):
    """超级管理员。"""
    from app.utils.security import hash_password
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
    """普通用户 A。"""
    from app.utils.security import hash_password
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
    """普通用户 B。"""
    from app.utils.security import hash_password
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


# ---------------------------------------------------------------------------
# 部门 CRUD
# ---------------------------------------------------------------------------

class TestDepartmentCRUD:
    def test_create_root_department(self, app, admin):
        dept = department_service.create_department("总公司", None, admin)
        assert dept.id is not None
        assert dept.name == "总公司"
        assert dept.parent_id is None

    def test_create_sub_department(self, app, admin):
        root = department_service.create_department("总公司", None, admin)
        sub = department_service.create_department("技术部", root.id, admin)
        assert sub.parent_id == root.id

    def test_same_level_duplicate_name(self, app, admin):
        root = department_service.create_department("总公司", None, admin)
        department_service.create_department("技术部", root.id, admin)
        with pytest.raises(ApiError, match="同级已存在同名部门"):
            department_service.create_department("技术部", root.id, admin)

    def test_non_admin_cannot_create_root(self, app, user_a):
        with pytest.raises(ApiError, match="仅超级管理员可创建根部门"):
            department_service.create_department("总公司", None, user_a)

    def test_update_department(self, app, admin):
        dept = department_service.create_department("技术部", None, admin)
        updated = department_service.update_department(dept.id, "研发部", 5, admin)
        assert updated.name == "研发部"
        assert updated.sort_order == 5

    def test_delete_department_cascades_children(self, app, admin):
        root = department_service.create_department("总公司", None, admin)
        sub = department_service.create_department("技术部", root.id, admin)
        root_id, sub_id = root.id, sub.id
        department_service.delete_department(root_id, admin)
        # 用查询而非 session.get 避免 identity map 残留导致 ObjectDeletedError
        assert (
            db.session.query(Department).filter_by(id=root_id).first() is None
        )
        assert (
            db.session.query(Department).filter_by(id=sub_id).first() is None
        )

    def test_delete_nonempty_department_rejected(self, app, admin):
        """部门（含子孙）下存在正常文件时禁止删除，防止孤儿文件。"""
        from werkzeug.datastructures import FileStorage

        root = department_service.create_department("总公司", None, admin)
        sub = department_service.create_department("技术部", root.id, admin)
        sub.storage_quota = 1024 * 1024
        db.session.commit()
        fs = FileStorage()
        fs.filename = "a.txt"
        fs.stream = io.BytesIO(b"data")
        file_service.upload_file(admin, fs, department_id=sub.id)

        with pytest.raises(ApiError) as exc:
            department_service.delete_department(root.id, admin)
        assert exc.value.code == 3310
        # 拒绝后部门仍然存在
        assert db.session.get(Department, root.id) is not None
        assert db.session.get(Department, sub.id) is not None

    def test_delete_empty_department_cleans_relations(self, app, admin, user_a):
        """空部门删除时成员/管理员/权限关联被显式清理（SQLite 外键 CASCADE 不生效）。"""
        root = department_service.create_department("总公司", None, admin)
        root_id = root.id
        department_service.add_member(root_id, user_a.id, "员工", admin)
        permission_service.grant_permission(
            user_a.id, root_id, None, "read_only", admin
        )
        db.session.add(DepartmentAdmin(
            department_id=root_id, user_id=user_a.id,
            scope="self", granted_by=admin.id,
        ))
        db.session.commit()

        department_service.delete_department(root_id, admin)

        assert db.session.query(DepartmentMember).filter_by(
            department_id=root_id
        ).count() == 0
        assert db.session.query(DepartmentAdmin).filter_by(
            department_id=root_id
        ).count() == 0
        assert db.session.query(FilePermission).filter_by(
            department_id=root_id
        ).count() == 0

    def test_move_department_prevents_cycle(self, app, admin):
        root = department_service.create_department("总公司", None, admin)
        sub = department_service.create_department("技术部", root.id, admin)
        with pytest.raises(ApiError, match="不能将部门移动到自身或其子部门"):
            department_service.move_department(root.id, sub.id, admin)


# ---------------------------------------------------------------------------
# 成员管理
# ---------------------------------------------------------------------------

class TestDepartmentMembers:
    def test_add_member(self, app, admin, user_a):
        dept = department_service.create_department("技术部", None, admin)
        member = department_service.add_member(dept.id, user_a.id, "工程师", admin)
        assert member.department_id == dept.id
        assert member.user_id == user_a.id

    def test_add_duplicate_member(self, app, admin, user_a):
        dept = department_service.create_department("技术部", None, admin)
        department_service.add_member(dept.id, user_a.id, "工程师", admin)
        with pytest.raises(ApiError, match="该用户已是部门成员"):
            department_service.add_member(dept.id, user_a.id, "工程师", admin)

    def test_remove_member(self, app, admin, user_a):
        dept = department_service.create_department("技术部", None, admin)
        department_service.add_member(dept.id, user_a.id, "工程师", admin)
        department_service.remove_member(dept.id, user_a.id, admin)
        assert (
            db.session.query(DepartmentMember)
            .filter_by(department_id=dept.id, user_id=user_a.id)
            .first()
            is None
        )

    def test_non_admin_cannot_manage_members(self, app, admin, user_a, user_b):
        dept = department_service.create_department("技术部", None, admin)
        with pytest.raises(ApiError, match="无权管理"):
            department_service.add_member(dept.id, user_b.id, "员工", user_a)


# ---------------------------------------------------------------------------
# 管理员委派
# ---------------------------------------------------------------------------

class TestAdminDelegation:
    def test_super_admin_grants_admin(self, app, admin, user_a):
        dept = department_service.create_department("技术部", None, admin)
        admin_rec = permission_service.grant_admin(dept.id, user_a.id, "self_and_sub", admin)
        assert admin_rec.scope == "self_and_sub"

    def test_dept_admin_can_manage_subdept(self, app, admin, user_a, user_b):
        root = department_service.create_department("总公司", None, admin)
        tech = department_service.create_department("技术部", root.id, admin)
        permission_service.grant_admin(tech.id, user_a.id, "self_and_sub", admin)
        # user_a 是技术部管理员，可创建子部门
        sub = department_service.create_department("前端组", tech.id, user_a)
        assert sub.parent_id == tech.id

    def test_dept_admin_cannot_manage_sibling(self, app, admin, user_a):
        root = department_service.create_department("总公司", None, admin)
        tech = department_service.create_department("技术部", root.id, admin)
        market = department_service.create_department("市场部", root.id, admin)
        permission_service.grant_admin(tech.id, user_a.id, "self_and_sub", admin)
        # user_a 是技术部管理员，不能管理市场部
        with pytest.raises(ApiError, match="无权管理"):
            department_service.create_department("销售组", market.id, user_a)

    def test_scope_self_only_manages_own_dept(self, app, admin, user_a):
        root = department_service.create_department("总公司", None, admin)
        tech = department_service.create_department("技术部", root.id, admin)
        sub = department_service.create_department("前端组", tech.id, admin)
        permission_service.grant_admin(tech.id, user_a.id, "self", admin)
        # scope=self 不能管理子部门
        with pytest.raises(ApiError, match="无权管理"):
            department_service.create_department("Web组", sub.id, user_a)


# ---------------------------------------------------------------------------
# 权限检查
# ---------------------------------------------------------------------------

class TestPermissionCheck:
    def test_super_admin_has_full_access(self, app, admin, user_a):
        dept = department_service.create_department("技术部", None, admin)
        assert permission_service.check_department_access(admin, dept.id, "write") is True

    def test_dept_admin_has_full_access(self, app, admin, user_a):
        dept = department_service.create_department("技术部", None, admin)
        permission_service.grant_admin(dept.id, user_a.id, "self_and_sub", admin)
        assert permission_service.check_department_access(user_a, dept.id, "write") is True

    def test_member_default_read_only(self, app, admin, user_a):
        dept = department_service.create_department("技术部", None, admin)
        department_service.add_member(dept.id, user_a.id, "员工", admin)
        assert permission_service.check_department_access(user_a, dept.id, "read") is True
        assert permission_service.check_department_access(user_a, dept.id, "write") is False

    def test_explicit_read_write_permission(self, app, admin, user_a):
        dept = department_service.create_department("技术部", None, admin)
        permission_service.grant_permission(
            user_a.id, dept.id, None, "read_write", admin
        )
        assert permission_service.check_department_access(user_a, dept.id, "write") is True

    def test_denied_overrides_everything(self, app, admin, user_a):
        dept = department_service.create_department("技术部", None, admin)
        department_service.add_member(dept.id, user_a.id, "员工", admin)
        permission_service.grant_permission(
            user_a.id, dept.id, None, "denied", admin
        )
        assert permission_service.check_department_access(user_a, dept.id, "read") is False
        assert permission_service.check_department_access(user_a, dept.id, "write") is False

    def test_non_member_no_access(self, app, admin, user_b):
        dept = department_service.create_department("技术部", None, admin)
        assert permission_service.check_department_access(user_b, dept.id, "read") is False

    def test_subdept_admin_inherits_access(self, app, admin, user_a):
        root = department_service.create_department("总公司", None, admin)
        tech = department_service.create_department("技术部", root.id, admin)
        sub = department_service.create_department("前端组", tech.id, admin)
        permission_service.grant_admin(tech.id, user_a.id, "self_and_sub", admin)
        # user_a 是技术部管理员(scope=self_and_sub)，可管理前端组
        assert permission_service.check_department_access(user_a, sub.id, "write") is True


# ---------------------------------------------------------------------------
# 部门文件上传
# ---------------------------------------------------------------------------

class TestDepartmentFileUpload:
    def _make_storage(self, file_storage, filename="test.txt", content=b"hello"):
        from io import BytesIO
        file_storage.filename = filename
        file_storage.stream = BytesIO(content)
        return file_storage

    def test_admin_can_upload_to_department(self, app, admin):
        dept = department_service.create_department("技术部", None, admin)
        dept.storage_quota = 1024 * 1024  # 1MB
        db.session.commit()

        from werkzeug.datastructures import FileStorage
        fs = FileStorage()
        self._make_storage(fs, "test.txt", b"hello")
        node = file_service.upload_file(admin, fs, department_id=dept.id)
        assert node.department_id == dept.id
        assert node.user_id == admin.id
        assert node.file_name == "test.txt"

    def test_member_with_write_perm_can_upload(self, app, admin, user_a):
        dept = department_service.create_department("技术部", None, admin)
        dept.storage_quota = 1024 * 1024
        db.session.commit()
        permission_service.grant_permission(
            user_a.id, dept.id, None, "read_write", admin
        )
        from werkzeug.datastructures import FileStorage
        fs = FileStorage()
        self._make_storage(fs, "report.txt", b"content")
        node = file_service.upload_file(user_a, fs, department_id=dept.id)
        assert node.department_id == dept.id

    def test_member_readonly_cannot_upload(self, app, admin, user_a):
        dept = department_service.create_department("技术部", None, admin)
        dept.storage_quota = 1024 * 1024
        db.session.commit()
        department_service.add_member(dept.id, user_a.id, "员工", admin)
        from werkzeug.datastructures import FileStorage
        fs = FileStorage()
        self._make_storage(fs, "report.txt", b"content")
        with pytest.raises(ApiError, match="无权上传到该部门"):
            file_service.upload_file(user_a, fs, department_id=dept.id)

    def test_department_quota_deducted(self, app, admin):
        dept = department_service.create_department("技术部", None, admin)
        dept.storage_quota = 1024 * 1024
        db.session.commit()
        from werkzeug.datastructures import FileStorage
        fs = FileStorage()
        self._make_storage(fs, "data.txt", b"x" * 100)
        file_service.upload_file(admin, fs, department_id=dept.id)
        db.session.refresh(dept)
        assert dept.used_storage == 100

    def test_personal_files_unchanged(self, app, admin):
        """1.0.0 兼容：无 department_id 的个人文件行为不变。"""
        from werkzeug.datastructures import FileStorage
        fs = FileStorage()
        self._make_storage(fs, "personal.txt", b"mine")
        node = file_service.upload_file(admin, fs)
        assert node.department_id is None
        assert node.user_id == admin.id
