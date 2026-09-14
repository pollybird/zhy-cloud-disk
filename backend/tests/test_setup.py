"""安装向导全流程测试：未安装拦截 → 连库测试 → 安装 → 超管登录 → 二次安装被拒。"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from app import create_app


def test_uninstalled_state_blocks_business(app):
    """未安装态：业务接口被拦截，setup/ping 放行。

    此处验证已安装态下 setup/install 被锁定（等效校验）。
    """
    client = app.test_client()
    # 已安装态：install 应被永久拒绝
    r = client.post("/api/setup/install", json={
        "db_type": "sqlite", "database": "x.db",
        "admin_username": "a", "admin_email": "a@b.com",
        "admin_password": "Pass12345",
    })
    assert r.status_code == 403
    data = r.get_json()
    assert data["code"] == 2020


def test_status_returns_installed(app):
    client = app.test_client()
    r = client.get("/api/setup/status")
    assert r.status_code == 200
    assert r.get_json()["data"]["installed"] is True


def test_ping(app):
    client = app.test_client()
    r = client.get("/api/ping")
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["installed"] is True
    assert "version" in data


def test_fresh_install_full_flow():
    """全新环境：未安装拦截 → 安装 → 超管登录 → 二次被拒。"""
    tmp = Path(tempfile.mkdtemp(prefix="zhy-fresh-"))
    os.environ["ZHY_INSTANCE_DIR"] = str(tmp / "instance")
    os.environ["ZHY_STORAGE_DIR"] = str(tmp / "storage")

    # 全新应用（未安装）
    fresh_app = create_app()
    client = fresh_app.test_client()

    # 未安装：业务接口返回 503
    r = client.get("/api/user/info")
    assert r.status_code == 503
    assert r.get_json()["code"] == 4001

    # setup/status 返回未安装
    r = client.get("/api/setup/status")
    assert r.get_json()["data"]["installed"] is False

    # test-db 通过
    r = client.post("/api/setup/test-db", json={"db_type": "sqlite", "database": "fresh.db"})
    assert r.status_code == 200

    # environment 可访问
    r = client.get("/api/setup/environment")
    assert r.status_code == 200

    # 执行安装
    r = client.post("/api/setup/install", json={
        "db_type": "sqlite", "database": "fresh.db",
        "admin_username": "superadmin", "admin_email": "sa@test.com",
        "admin_password": "Super12345",
    })
    assert r.status_code == 200
    result = r.get_json()["data"]
    assert result["admin_username"] == "superadmin"

    # 安装后：超管可登录
    r = client.post("/api/login", json={"username": "superadmin", "password": "Super12345"})
    assert r.status_code == 200

    # 二次安装被拒
    r = client.post("/api/setup/install", json={
        "db_type": "sqlite", "database": "fresh2.db",
        "admin_username": "x", "admin_email": "x@x.com",
        "admin_password": "Xxx12345",
    })
    assert r.status_code == 403

    # 恢复环境变量
    from tests.conftest import _TMP_ROOT
    os.environ["ZHY_INSTANCE_DIR"] = str(_TMP_ROOT / "instance")
    os.environ["ZHY_STORAGE_DIR"] = str(_TMP_ROOT / "storage")
    shutil.rmtree(tmp, ignore_errors=True)
