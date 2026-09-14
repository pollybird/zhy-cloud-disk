"""pytest 全局 fixture：临时 SQLite + 临时存储 + 已安装应用 + 认证客户端。

每个测试函数获得独立实例目录，互不干扰；安装在 session 级完成一次。
"""
import io
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# 必须在导入 create_app 前设置环境变量
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="zhy-test-"))
os.environ["ZHY_INSTANCE_DIR"] = str(_TMP_ROOT / "instance")
os.environ["ZHY_STORAGE_DIR"] = str(_TMP_ROOT / "storage")
os.environ["ZHY_ENV"] = "testing"
os.environ["ZHY_ALLOW_REGISTER"] = "true"

import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.services.setup_service import run_installation  # noqa: E402


@pytest.fixture(scope="session")
def app():
    """已安装的 Flask 应用（session 级共享）。"""
    _app = create_app()
    with _app.app_context():
        run_installation(_app, {
            "db_type": "sqlite",
            "database": "test.db",
            "admin_username": "admin",
            "admin_email": "admin@test.com",
            "admin_password": "Admin12345",
        })
    return _app


@pytest.fixture()
def client(app):
    """测试客户端；每函数自动回滚数据库变更。"""
    with app.app_context():
        yield app.test_client()


@pytest.fixture()
def admin_headers(app, client):
    """管理员 JWT 请求头。"""
    with app.app_context():
        r = client.post("/api/login", json={"username": "admin", "password": "Admin12345"})
        token = r.get_json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_refresh(app, client):
    """管理员 refresh token。"""
    with app.app_context():
        r = client.post("/api/login", json={"username": "admin", "password": "Admin12345"})
    return r.get_json()["data"]["refresh_token"]


@pytest.fixture()
def user_headers(app, client):
    """创建普通用户并返回其 JWT 请求头。"""
    with app.app_context():
        client.post("/api/register", json={
            "username": "testuser1",
            "email": "testuser1@test.com",
            "password": "Test12345",
        })
        r = client.post("/api/login", json={"username": "testuser1", "password": "Test12345"})
        token = r.get_json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def user2_headers(app, client):
    """第二个普通用户（用于越权测试）。"""
    with app.app_context():
        client.post("/api/register", json={
            "username": "testuser2",
            "email": "testuser2@test.com",
            "password": "Test12345",
        })
        r = client.post("/api/login", json={"username": "testuser2", "password": "Test12345"})
        token = r.get_json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def make_upload(content=b"hello", filename="test.txt"):
    """构造 multipart 文件元组。"""
    return (io.BytesIO(content), filename)


def cleanup_tmp():
    if _TMP_ROOT.exists():
        shutil.rmtree(_TMP_ROOT, ignore_errors=True)


def pytest_sessionfinish(session, exitstatus):
    cleanup_tmp()
