"""H1：环境变量静默安装必须拒绝默认/弱管理员密码，强随机密码可正常安装。"""
import pytest

from app import create_app
from app.services import setup_service
from app.services.setup_service import maybe_auto_install
from app.utils.errors import ApiError


@pytest.fixture()
def fresh_install_env(tmp_path, monkeypatch):
    """构造未安装的独立实例（与 session 级已安装应用隔离）。"""
    inst = tmp_path / "instance"
    storage = tmp_path / "storage"
    inst.mkdir()
    storage.mkdir()
    monkeypatch.setenv("ZHY_INSTANCE_DIR", str(inst))
    monkeypatch.setenv("ZHY_STORAGE_DIR", str(storage))
    for key in (
        "ZHY_DOCKER", "ZHY_DATABASE_URL", "ZHY_ADMIN_USERNAME",
        "ZHY_ADMIN_PASSWORD", "ZHY_ADMIN_EMAIL",
    ):
        monkeypatch.delenv(key, raising=False)
    app = create_app()
    return app, inst


_WEAK_PASSWORDS = [
    "Admin12345",      # 旧默认值
    "admin123",        # 常见弱口令
    "Admin2026xyz",    # 以 admin 开头即拒
    "password123",
    "12345678",
    "ChangeMe123",
]


@pytest.mark.parametrize("weak", _WEAK_PASSWORDS)
def test_auto_install_rejects_weak_password(fresh_install_env, monkeypatch, weak):
    app, inst = fresh_install_env
    monkeypatch.setenv("ZHY_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ZHY_ADMIN_PASSWORD", weak)
    with pytest.raises(ApiError) as exc:
        maybe_auto_install(app)
    assert exc.value.code == 2011
    # 拒绝后不得产生任何安装痕迹
    assert not (inst / "config.installed.json").exists()
    assert not setup_service.is_installed()


def test_docker_auto_install_rejects_weak_password(fresh_install_env, monkeypatch):
    """Docker 分支同样在连接数据库前拦截弱口令。"""
    app, inst = fresh_install_env
    monkeypatch.setenv("ZHY_DOCKER", "1")
    monkeypatch.setenv("ZHY_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ZHY_ADMIN_PASSWORD", "Admin12345")
    with pytest.raises(ApiError) as exc:
        maybe_auto_install(app)
    assert exc.value.code == 2011
    assert not (inst / "config.installed.json").exists()


def test_auto_install_accepts_strong_password(fresh_install_env, monkeypatch):
    app, inst = fresh_install_env
    strong = "Str0ng-Rand0m-Pw9x"
    monkeypatch.setenv("ZHY_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ZHY_ADMIN_PASSWORD", strong)

    assert maybe_auto_install(app) is True
    assert (inst / "config.installed.json").exists()
    assert setup_service.is_installed()

    # 安装后可用该密码登录
    client = app.test_client()
    r = client.post("/api/login", json={"username": "admin", "password": strong})
    assert r.status_code == 200
    assert r.get_json()["data"]["access_token"]
