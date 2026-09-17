"""审计日志单元测试。

覆盖：
- 权限/部门/成员操作产生日志
- 全局日志仅超管可查
- 部门日志需管理权限且包含子部门
- my-admin-depts / candidate-users 辅助接口
- 部门文件操作记录日志（个人文件不记录）
"""
import pytest

from app import create_app
from app.extensions import db
from app.models.user import User
from app.services import department_service, file_service, permission_service
from app.services.setup_service import run_installation
from app.utils.security import hash_password


@pytest.fixture
def app(tmp_path, monkeypatch):
    """完整安装流程创建的测试应用（部门功能开启）。

    每个测试重定向独立实例目录，安装标记与 SQLite 文件互不干扰。
    """
    monkeypatch.setenv("ZHY_INSTANCE_DIR", str(tmp_path / "instance"))
    _app = create_app({
        "DEPARTMENT_DRIVE_ENABLED": True,
        "STORAGE_DIR": str(tmp_path / "storage"),
        "TESTING": True,
    })
    with _app.app_context():
        run_installation(_app, {
            "db_type": "sqlite",
            "database": "test_log.db",
            "admin_username": "admin",
            "admin_email": "admin@test.com",
            "admin_password": "Admin12345",
            "department_drive_enabled": True,
        })
        yield _app


@pytest.fixture
def admin(app):
    """安装时创建的超级管理员。"""
    return db.session.query(User).filter_by(username="admin").first()


@pytest.fixture
def user_a(app):
    user = User(
        username="userA", password=hash_password("Pass1234"),
        email="a@test.com", role="user", status="active",
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def user_b(app):
    user = User(
        username="userB", password=hash_password("Pass1234"),
        email="b@test.com", role="user", status="active",
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def tree(app, admin):
    """admin - 根部门 R - 子部门 S。A 为 R 管理员（self_and_sub）。"""
    root = department_service.create_department("研发部", None, admin)
    sub = department_service.create_department("后端组", root.id, admin)
    return root, sub


class TestLogRecording:
    def test_permission_grant_writes_log(self, app, admin, user_a, tree):
        root, _ = tree
        permission_service.grant_permission(user_a.id, root.id, None, "read_write", admin)
        from app.models.operation_log import OperationLog
        log = (
            db.session.query(OperationLog)
            .filter_by(action="permission_grant", department_id=root.id)
            .first()
        )
        assert log is not None
        assert log.user_id == admin.id

    def test_admin_grant_and_revoke_writes_log(self, app, admin, user_a, tree):
        root, _ = tree
        permission_service.grant_admin(root.id, user_a.id, "self_and_sub", admin)
        permission_service.revoke_admin(root.id, user_a.id, admin)
        from app.models.operation_log import OperationLog
        actions = {
            r[0]
            for r in db.session.query(OperationLog.action).filter(
                OperationLog.department_id == root.id,
                OperationLog.action.in_(["admin_grant", "admin_revoke"]),
            ).all()
        }
        assert actions == {"admin_grant", "admin_revoke"}

    def test_member_ops_write_log(self, app, admin, user_a, tree):
        root, _ = tree
        department_service.add_member(root.id, user_a.id, "工程师", admin)
        department_service.update_member(root.id, user_a.id, "高级工程师", admin)
        department_service.remove_member(root.id, user_a.id, admin)
        from app.models.operation_log import OperationLog
        actions = {
            r[0]
            for r in db.session.query(OperationLog.action).filter(
                OperationLog.department_id == root.id,
                OperationLog.action.like("member_%"),
            ).all()
        }
        assert actions == {"member_add", "member_remove", "member_update"}

    def test_dept_crud_writes_log(self, app, admin, tree):
        root, sub = tree
        sub_id = sub.id
        department_service.update_department(sub_id, "前端组", 1, admin)
        department_service.delete_department(sub_id, admin)
        from app.models.operation_log import OperationLog
        assert db.session.query(OperationLog).filter_by(
            action="department_update", target_id=sub_id
        ).first() is not None
        assert db.session.query(OperationLog).filter_by(
            action="department_delete", target_id=sub_id
        ).first() is not None

    def test_dept_file_upload_writes_log_personal_not(self, app, admin, user_a, tree):
        """部门文件上传记录日志；个人文件上传不记录（1.0.0 行为不变）。"""
        from io import BytesIO

        from werkzeug.datastructures import FileStorage

        root, _ = tree
        permission_service.grant_permission(user_a.id, root.id, None, "read_write", admin)
        root.storage_quota = 1024 * 1024
        db.session.commit()
        dept_node = file_service.upload_file(
            user_a, FileStorage(stream=BytesIO(b"dept data"), filename="dept.txt"),
            None, department_id=root.id,
        )
        personal_node = file_service.upload_file(
            user_a, FileStorage(stream=BytesIO(b"my data"), filename="mine.txt")
        )
        from app.models.operation_log import OperationLog
        dept_log = OperationLog.query.filter_by(
            action="file_upload", target_id=dept_node.id
        ).first()
        assert dept_log is not None and dept_log.department_id == root.id
        assert OperationLog.query.filter_by(
            action="file_upload", target_id=personal_node.id
        ).first() is None


class TestLogQuery:
    def test_global_logs_admin_only(self, app, client, admin, user_a, tree):
        root, _ = tree
        permission_service.grant_permission(user_a.id, root.id, None, "read_only", admin)

        r = client.post("/api/login", json={"username": "admin", "password": "Admin12345"})
        admin_headers = {"Authorization": f"Bearer {r.get_json()['data']['access_token']}"}
        r = client.get("/api/log/global", headers=admin_headers)
        assert r.status_code == 200
        body = r.get_json()
        assert body["code"] == 0
        actions = [i["action"] for i in body["data"]["items"]]
        assert "permission_grant" in actions
        assert all("username" in i for i in body["data"]["items"])

        # 普通用户（即使被委派管理员）不可查全局
        r = client.post("/api/login", json={"username": "userA", "password": "Pass1234"})
        user_headers = {"Authorization": f"Bearer {r.get_json()['data']['access_token']}"}
        r = client.get("/api/log/global", headers=user_headers)
        assert r.status_code == 403

    def test_department_logs_requires_manage(self, app, client, admin, user_a, user_b, tree):
        root, _ = tree
        department_service.add_member(root.id, user_b.id, "", admin)

        r = client.post("/api/login", json={"username": "userB", "password": "Pass1234"})
        b_headers = {"Authorization": f"Bearer {r.get_json()['data']['access_token']}"}
        r = client.get(f"/api/log/department/{root.id}", headers=b_headers)
        assert r.status_code == 403

    def test_department_logs_include_subtree(self, app, client, admin, user_a, tree):
        root, sub = tree
        # 委派 A 为根部门管理员（self_and_sub），在子部门授权产生日志
        permission_service.grant_admin(root.id, user_a.id, "self_and_sub", admin)
        permission_service.grant_permission(user_a.id, sub.id, None, "read_write", admin)

        r = client.post("/api/login", json={"username": "userA", "password": "Pass1234"})
        a_headers = {"Authorization": f"Bearer {r.get_json()['data']['access_token']}"}
        r = client.get(f"/api/log/department/{root.id}", headers=a_headers)
        assert r.status_code == 200
        actions = [i["action"] for i in r.get_json()["data"]["items"]]
        assert "permission_grant" in actions

    def test_action_filter(self, app, client, admin, user_a, tree):
        root, _ = tree
        department_service.add_member(root.id, user_a.id, "", admin)
        permission_service.grant_permission(user_a.id, root.id, None, "read_only", admin)

        r = client.post("/api/login", json={"username": "admin", "password": "Admin12345"})
        headers = {"Authorization": f"Bearer {r.get_json()['data']['access_token']}"}
        r = client.get("/api/log/global?action=member_add", headers=headers)
        items = r.get_json()["data"]["items"]
        assert items and all(i["action"] == "member_add" for i in items)


class TestAuxEndpoints:
    def test_my_admin_depts(self, app, client, admin, user_a, tree):
        root, _ = tree
        permission_service.grant_admin(root.id, user_a.id, "self", admin)

        r = client.post("/api/login", json={"username": "userA", "password": "Pass1234"})
        headers = {"Authorization": f"Bearer {r.get_json()['data']['access_token']}"}
        r = client.get("/api/permission/my-admin-depts", headers=headers)
        assert r.status_code == 200
        data = r.get_json()["data"]
        assert {"department_id": root.id, "scope": "self"} in data

    def test_candidate_users_exclude_members(self, app, client, admin, user_a, user_b, tree):
        root, _ = tree
        department_service.add_member(root.id, user_a.id, "", admin)

        r = client.post("/api/login", json={"username": "admin", "password": "Admin12345"})
        headers = {"Authorization": f"Bearer {r.get_json()['data']['access_token']}"}
        r = client.get(f"/api/department/{root.id}/candidate-users", headers=headers)
        ids = [u["id"] for u in r.get_json()["data"]]
        assert user_a.id not in ids
        assert user_b.id in ids

        # 成员（非管理员）不可调用
        r = client.post("/api/login", json={"username": "userA", "password": "Pass1234"})
        a_headers = {"Authorization": f"Bearer {r.get_json()['data']['access_token']}"}
        r = client.get(f"/api/department/{root.id}/candidate-users", headers=a_headers)
        assert r.status_code == 403
