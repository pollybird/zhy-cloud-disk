"""1.3.0：监控指标、后台设置校验、备份恢复（本地/SFTP/FTP）。

SFTP 用 paramiko 在本机临时端口起内嵌 SSH/SFTP 服务；FTP 用标准库 socket
实现最小被动模式服务器。备份恢复往返使用独立的临时 SQLite 应用。
"""
import io
import os
import shutil
import socket
import socketserver
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.services import backup_service, metrics_service, setting_service
from app.utils.security import hash_password


# ===========================================================================
# 监控指标
# ===========================================================================

def test_metrics_endpoint_shape_and_permission(app, client, admin_headers, user_headers):
    r = client.get("/api/admin/metrics", headers=admin_headers)
    assert r.status_code == 200
    d = r.get_json()["data"]
    assert set(["cpu", "memory", "disk", "online_users", "traffic", "storage"]).issubset(d)
    assert d["cpu"]["percent"] >= 0
    assert d["memory"]["total"] > 0
    assert d["disk"]["percent"] >= 0
    assert len(d["traffic"]["days"]) == 7
    assert client.get("/api/admin/metrics", headers=user_headers).status_code == 403
    assert client.get("/api/admin/metrics").status_code == 401


def test_cgroup_v2_memory_parse(monkeypatch, app):
    files = {
        "/sys/fs/cgroup/memory.max": "1073741824\n",
        "/sys/fs/cgroup/memory.current": "536870912\n",
    }
    monkeypatch.setattr(metrics_service, "_read_text", lambda p: files.get(p))
    with app.app_context():
        m = metrics_service.memory_usage()
    assert m["cgroup"] is True
    assert m["total"] == 1073741824 and m["percent"] == 50.0


def test_cgroup_v1_memory_parse(monkeypatch, app):
    files = {
        "/sys/fs/cgroup/memory/memory.limit_in_bytes": "1073741824\n",
        "/sys/fs/cgroup/memory/memory.usage_in_bytes": "268435456\n",
        "/sys/fs/cgroup/memory/memory.stat": "cache 0\ninactive_file 65536\n",
    }
    monkeypatch.setattr(metrics_service, "_read_text", lambda p: files.get(p))
    with app.app_context():
        m = metrics_service.memory_usage()
    assert m["cgroup"] is True
    assert m["used"] == 268435456 - 65536


def test_cgroup_cpu_quota_parse(monkeypatch):
    monkeypatch.setattr(metrics_service, "_read_text", lambda p: "250000 100000\n" if p.endswith("cpu.max") else None)
    assert metrics_service._parse_cpu_quota_v2() == 2.5
    monkeypatch.setattr(metrics_service, "_read_text", lambda p: "max\n" if p.endswith("cpu.max") else None)
    assert metrics_service._parse_cpu_quota_v2() is None

    files = {
        "/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "50000\n",
        "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000\n",
    }
    monkeypatch.setattr(metrics_service, "_read_text", lambda p: files.get(p))
    assert metrics_service._parse_cpu_quota_v1() == 0.5


def test_online_counted_after_authenticated_request(app, client, admin_headers):
    client.get("/api/user/info", headers=admin_headers)
    with app.app_context():
        assert metrics_service.online_user_count() >= 1


def test_traffic_accumulate_flush_and_purge(app):
    with app.app_context():
        before = metrics_service.traffic_stats()["today_up"]
        metrics_service.record_traffic(up=2048, down=1024)
        pending = metrics_service.traffic_stats()
        assert pending["today_up"] >= before + 2048
        assert pending["today_down"] >= 1024
        metrics_service.flush_traffic()
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        row = db.session.get(SystemSetting, f"traffic_up:{day}")
        assert row is not None and int(row.value) >= before + 2048

        # 超期键清理（31 天前）
        old_day = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y%m%d")
        db.session.add(SystemSetting(key=f"traffic_up:{old_day}", value="1"))
        db.session.commit()
        metrics_service._purge_old_traffic()
        db.session.commit()
        assert db.session.get(SystemSetting, f"traffic_up:{old_day}") is None


# ===========================================================================
# 备份设置校验
# ===========================================================================

def test_backup_settings_validation(app, client, admin_headers):
    def put(payload):
        return client.put("/api/admin/settings", json=payload, headers=admin_headers)

    r = put({"backup_port": 70000})
    assert r.status_code == 400 and r.get_json()["code"] == 1222

    r = put({"backup_target": "remote"})  # 未配置 host
    assert r.status_code == 400 and r.get_json()["code"] == 1223

    r = put({"backup_protocol": "tftp"})
    assert r.status_code == 400 and r.get_json()["code"] == 1222

    r = put({
        "backup_target": "remote", "backup_protocol": "sftp",
        "backup_host": "127.0.0.1", "backup_port": 2222,
        "backup_username": "bk", "backup_password": "secret",
        "backup_remote_dir":"/zhy-bk",
    })
    assert r.status_code == 200, r.get_json()

    with app.app_context():
        cfg = setting_service.get_backup_remote_config()
        assert cfg["target"] == "remote" and cfg["port"] == 2222
        assert cfg["password"] == "secret"
        assert "backup_password" not in setting_service.admin_settings()
        assert setting_service.admin_settings()["backup_has_password"] is True

        # 空密码 = 保持原密码
        setting_service.update_admin_settings({"backup_password": ""})
        assert setting_service.get_backup_remote_config()["password"] == "secret"

        # 复位为本地，避免污染其他测试
        setting_service.set_raw(setting_service.KEY_BACKUP_TARGET, "local")


# ===========================================================================
# 独立临时应用（备份恢复往返，不碰主测试库）
# ===========================================================================

@pytest.fixture(scope="module")
def iso(tmp_path_factory):
    from app import create_app
    from app.extensions import scheduler

    root = tmp_path_factory.mktemp("iso-backup")
    db_path = root / "iso.db"
    storage = root / "storage"
    application = create_app({
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        "STORAGE_DIR": str(storage),
        "ENV": "testing",
    })
    with application.app_context():
        db.create_all()
        db.session.add(User(
            username="admin", email="admin@iso.local",
            password=hash_password("Admin12345"), role="admin",
            status="active", total_storage=5 * 1024 ** 3,
        ))
        db.session.commit()
    yield application
    if scheduler.running:
        scheduler.shutdown(wait=False)


def _iso_client_headers(iso):
    c = iso.test_client()
    tok = c.post("/api/login", json={
        "username": "admin", "password": "Admin12345",
    }).get_json()["data"]["access_token"]
    return c, {"Authorization": f"Bearer {tok}"}


# iso 为模块级共享应用：每个用例前清空备份记录、远端配置与备份目录，
# 避免上一个用例的 remote/dead-port 设置污染后续用例。
_ISO_RESET_KEYS = (
    setting_service.KEY_BACKUP_PROTOCOL,
    setting_service.KEY_BACKUP_HOST,
    setting_service.KEY_BACKUP_PORT,
    setting_service.KEY_BACKUP_USERNAME,
    setting_service.KEY_BACKUP_PASSWORD_ENC,
    setting_service.KEY_BACKUP_REMOTE_DIR,
)


@pytest.fixture(autouse=True)
def _isolate_iso_backups(request):
    if "iso" not in request.fixturenames:
        yield
        return
    iso = request.getfixturevalue("iso")
    with iso.app_context():
        backup_service.BackupRecord.query.delete()
        db.session.commit()
        for key in _ISO_RESET_KEYS:
            row = db.session.get(SystemSetting, key)
            if row is not None:
                db.session.delete(row)
        db.session.commit()
        setting_service.set_raw(setting_service.KEY_BACKUP_TARGET, "local")
        # 清缓存（set_raw 已刷新 target，其余键直接删缓存）
        from app.services.cache_service import cache_delete
        for key in _ISO_RESET_KEYS:
            cache_delete(f"setting:{key}")
        bdir = backup_service.backup_dir()
        if bdir.exists():
            for p in bdir.iterdir():
                if p.is_file():
                    p.unlink()
                else:
                    shutil.rmtree(p, ignore_errors=True)
    yield


# ---------------------------------------------------------------------------
# SQLite 备份/恢复往返
# ---------------------------------------------------------------------------

def test_sqlite_backup_restore_roundtrip(iso):
    with iso.app_context():
        db.session.add(User(
            username="bkuser", email="bk@iso.local",
            password=hash_password("Test12345"),
        ))
        db.session.commit()

        rec = backup_service.create_backup("manual")
        assert rec.status == "done" and rec.location == "local"
        zipp = backup_service.backup_dir() / rec.filename
        assert zipp.is_file() and rec.file_size == zipp.stat().st_size
        with zipfile.ZipFile(zipp) as z:
            names = z.namelist()
            assert "zhycloud.db" in names and "manifest.json" in names

        # 改动数据
        db.session.query(User).filter_by(username="bkuser").delete()
        db.session.query(User).filter_by(username="admin").update({"email": "x@iso.local"})
        db.session.commit()

        result = backup_service.restore_from_package(zipp)
        assert result["db_type"] == "sqlite" and result["restart_required"] is True
        assert result["rollback_file"]
        db.session.remove()
        assert db.session.query(User).filter_by(username="bkuser").count() == 1
        assert db.session.query(User).filter_by(username="admin").first().email == "admin@iso.local"


def test_invalid_packages_rejected(iso):
    with iso.app_context():
        bdir = backup_service.backup_dir()
        bad = bdir / "bad-no-manifest.zip"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("zhycloud.db", b"xx")
        with pytest.raises(backup_service.BackupError, match="manifest"):
            backup_service.restore_from_package(bad)
        bad.unlink()

        # 先取一个合法包再篡改数据库部分
        rec = backup_service.create_backup("manual")
        good = bdir / rec.filename
        tampered = bdir / "tampered.zip"
        with zipfile.ZipFile(good) as zin, zipfile.ZipFile(tampered, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "zhycloud.db":
                    data = b"z" + data[1:]
                zout.writestr(item, data)
        with pytest.raises(backup_service.BackupError, match="校验失败"):
            backup_service.restore_from_package(tampered)
        tampered.unlink()


def test_scheduled_prune_keeps_count(iso):
    with iso.app_context():
        for i in range(3):
            db.session.add(backup_service.BackupRecord(
                filename=f"zhy-backup-2026090{i+1}-00000{i}-sqlite.zip",
                file_size=1, db_type="sqlite", trigger="schedule",
                status="done", location="local",
            ))
        db.session.commit()
        removed = backup_service.prune_scheduled(2)
        assert removed == 1
        assert db.session.query(backup_service.BackupRecord).filter_by(
            trigger="schedule").count() == 2


def test_postgresql_backup_rejected(iso):
    original_uri = iso.config["SQLALCHEMY_DATABASE_URI"]
    iso.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://x/y"
    try:
        with iso.app_context():
            with pytest.raises(backup_service.BackupError, match="暂不支持"):
                backup_service.create_backup("manual")
    finally:
        iso.config["SQLALCHEMY_DATABASE_URI"] = original_uri


# ---------------------------------------------------------------------------
# 内嵌 SFTP 服务器（paramiko）
# ---------------------------------------------------------------------------

try:
    import paramiko as _paramiko

    class _SftpInterface(_paramiko.SFTPServerInterface):
        def __init__(self, server, root):
            super().__init__(server)
            self.root = root

        def _local(self, p):
            p = p or "/"
            if not p.startswith("/"):
                p = "/" + p
            return os.path.normpath(os.path.join(self.root, p.lstrip("/")))

        def list_folder(self, p):
            try:
                out = []
                base = self._local(p)
                for name in os.listdir(base):
                    attr = _paramiko.SFTPAttributes.from_stat(os.stat(os.path.join(base, name)))
                    attr.filename = name
                    out.append(attr)
                return out
            except OSError:
                return _paramiko.SFTP_NO_SUCH_FILE

        def stat(self, p):
            try:
                return _paramiko.SFTPAttributes.from_stat(os.stat(self._local(p)))
            except OSError:
                return _paramiko.SFTP_NO_SUCH_FILE

        lstat = stat

        def open(self, p, flags, attr):
            try:
                mode = os.O_RDONLY
                if flags & os.O_WRONLY:
                    mode = os.O_WRONLY
                if flags & os.O_RDWR:
                    mode = os.O_RDWR
                if flags & os.O_CREAT:
                    mode |= os.O_CREAT
                if flags & os.O_TRUNC:
                    mode |= os.O_TRUNC
                if flags & os.O_APPEND:
                    mode |= os.O_APPEND
                fd = os.open(self._local(p), mode, 0o644)
                handle = _paramiko.SFTPHandle(flags)
                writable = flags & (os.O_WRONLY | os.O_RDWR)
                handle.writefile = os.fdopen(fd, "ab" if (flags & os.O_APPEND) else "wb") if writable else None
                handle.readfile = None if writable else os.fdopen(fd, "rb")
                return handle
            except OSError:
                return _paramiko.SFTP_PERMISSION_DENIED

        def remove(self, p):
            try:
                os.remove(self._local(p))
                return _paramiko.SFTP_OK
            except OSError:
                return _paramiko.SFTP_FAILURE

        def mkdir(self, p, attr):
            try:
                os.mkdir(self._local(p))
                return _paramiko.SFTP_OK
            except OSError:
                return _paramiko.SFTP_FAILURE

        def rmdir(self, p):
            try:
                os.rmdir(self._local(p))
                return _paramiko.SFTP_OK
            except OSError:
                return _paramiko.SFTP_FAILURE

        def rename(self, src, dst):
            try:
                os.rename(self._local(src), self._local(dst))
                return _paramiko.SFTP_OK
            except OSError:
                return _paramiko.SFTP_FAILURE

        def chattr(self, p, attr):
            return _paramiko.SFTP_OK

        def canonicalize(self, p):
            return p or "/"

    class _SshAuth(_paramiko.ServerInterface):
        def __init__(self, users):
            self.users = users

        def check_channel_request(self, kind, chanid):
            return _paramiko.OPEN_SUCCEEDED if kind == "session" else _paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

        def check_auth_password(self, username, password):
            return _paramiko.AUTH_SUCCESSFUL if self.users.get(username) == password else _paramiko.AUTH_FAILED

        def check_auth_publickey(self, username, key):
            return _paramiko.AUTH_FAILED

        def get_allowed_auths(self, username):
            return "password"

        # 不覆盖 check_channel_subsystem_request：默认实现会按
        # set_subsystem_handler 注册表启动 SFTPServer（自行覆盖只返回 True
        # 会导致处理器不启动、客户端永远等不到版本包）。

    class _SshHandler(socketserver.BaseRequestHandler):
        def handle(self):
            transport = _paramiko.Transport(self.request)
            transport.add_server_key(self.server.host_key)
            transport.set_subsystem_handler(
                "sftp", _paramiko.SFTPServer, _SftpInterface, self.server.root)
            transport.start_server(server=_SshAuth(self.server.users))
            while transport.is_active():
                transport.join(1)
            transport.close()

    class _SshServer(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

        def __init__(self, root, users):
            self.root = str(root)
            self.users = users
            self.host_key = _paramiko.RSAKey.generate(2048)
            super().__init__(("127.0.0.1", 0), _SshHandler)

except ImportError:  # pragma: no cover
    _SshServer = None


@pytest.fixture
def sftp_server(tmp_path):
    root = tmp_path / "sftproot"
    root.mkdir(parents=True, exist_ok=True)
    server = _SshServer(root, {"tester": "testpwd"})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def _sftp_uploader(port, remote_dir="/zhy-bk"):
    return backup_service.SftpUploader(
        "127.0.0.1", port, "tester", "testpwd", remote_dir)


def test_sftp_uploader_cycle(sftp_server, tmp_path):
    uploader = _sftp_uploader(sftp_server)
    assert "SFTP" in uploader.test_connection()

    payload = os.urandom(3000)
    local = tmp_path / "a.zip"
    local.write_bytes(payload)
    uploader.upload(local, "zhy-backup-20260919-000000-sqlite.zip")

    files = uploader.list_files()
    assert len(files) == 1 and files[0]["size"] == 3000

    got = tmp_path / "downloaded.zip"
    uploader.download(files[0]["name"], got)
    assert got.read_bytes() == payload

    uploader.delete(files[0]["name"])
    assert uploader.list_files() == []


def test_sftp_bad_password_and_dead_host(sftp_server):
    bad = backup_service.SftpUploader("127.0.0.1", sftp_server, "tester", "wrong", "/zhy-bk")
    with pytest.raises(backup_service.BackupError, match="认证失败"):
        bad.test_connection()

    dead = backup_service.SftpUploader("127.0.0.1", 1, "u", "p", "/zhy-bk")
    with pytest.raises(backup_service.BackupError):
        dead.test_connection()


# ---------------------------------------------------------------------------
# 内嵌最小 FTP 服务器（标准库，被动模式）
# ---------------------------------------------------------------------------

class _FtpHandler(socketserver.StreamRequestHandler):
    def setup(self):
        super().setup()
        self.cwd = "/"
        self.authed = False
        self.user = ""
        self._data = None

    def _send(self, code, msg=""):
        self.wfile.write(f"{code} {msg}\r\n".encode())
        self.wfile.flush()

    def _path(self, arg):
        if arg.startswith("/"):
            p = arg
        else:
            p = self.cwd.rstrip("/") + "/" + arg
        return os.path.normpath(os.path.join(self.server.root, p.lstrip("/")))

    def _start_data(self):
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        _, port = sock.getsockname()
        ready = threading.Event()

        def accept():
            ready.set()
            conn, _ = sock.accept()
            sock.close()
            self._data = conn

        threading.Thread(target=accept, daemon=True).start()
        ready.wait(1)
        p1, p2 = port // 256, port % 256
        self._send(227, f"Entering Passive Mode (127,0,0,1,{p1},{p2}).")

    def _wait_data(self, timeout=5):
        deadline = time.time() + timeout
        while self._data is None and time.time() < deadline:
            time.sleep(0.02)
        return self._data is not None

    def handle(self):
        self._send(220, "ready")
        while True:
            line = self.rfile.readline()
            if not line:
                break
            cmd, _, arg = line.decode(errors="ignore").rstrip("\r\n").partition(" ")
            cmd = cmd.upper()
            if cmd == "USER":
                self.user = arg
                self._send(331, "need password")
            elif cmd == "PASS":
                if self.server.users.get(self.user) == arg:
                    self.authed = True
                    self._send(230, "welcome")
                else:
                    self._send(530, "bad credentials")
            elif not self.authed:
                self._send(530, "login first")
            elif cmd in ("SYST",):
                self._send(215, "UNIX Type: L8")
            elif cmd == "FEAT":
                self.wfile.write(b"211-Features:\r\n211 End\r\n")
                self.wfile.flush()
            elif cmd in ("NOOP",):
                self._send(200, "ok")
            elif cmd == "TYPE":
                self._send(200, "type set")
            elif cmd == "PWD" or cmd == "XPWD":
                self._send(257, f'"{self.cwd}" is cwd')
            elif cmd == "CWD":
                target = self._path(arg)
                if os.path.isdir(target):
                    self.cwd = arg if arg.startswith("/") else self.cwd.rstrip("/") + "/" + arg
                    self._send(250, "ok")
                else:
                    self._send(550, "no such dir")
            elif cmd in ("MKD", "XMKD"):
                try:
                    os.makedirs(self._path(arg), exist_ok=False)
                    self._send(257, f'"{arg}" created')
                except OSError:
                    self._send(550, "mkdir failed")
            elif cmd == "PASV":
                self._start_data()
            elif cmd == "STOR":
                if not self._wait_data():
                    self._send(425, "no data connection")
                    continue
                self._send(150, "ready")
                with self._data.makefile("rb") as f:
                    payload = f.read()
                self._data.close()
                self._data = None
                with open(self._path(arg), "wb") as f:
                    f.write(payload)
                self._send(226, "done")
            elif cmd == "RETR":
                if not self._wait_data() or not os.path.isfile(self._path(arg)):
                    self._send(550, "unavailable")
                    continue
                self._send(150, "ready")
                with open(self._path(arg), "rb") as f:
                    self._data.sendall(f.read())
                self._data.close()
                self._data = None
                self._send(226, "done")
            elif cmd == "DELE":
                try:
                    os.remove(self._path(arg))
                    self._send(250, "deleted")
                except OSError:
                    self._send(550, "failed")
            elif cmd in ("RMD", "XRMD"):
                try:
                    os.rmdir(self._path(arg))
                    self._send(250, "removed")
                except OSError:
                    self._send(550, "failed")
            elif cmd in ("NLST", "LIST"):
                if not self._wait_data():
                    self._send(425, "no data connection")
                    continue
                self._send(150, "ready")
                names = os.listdir(self._path(self.cwd))
                body = ("".join(f"{n}\r\n" for n in names)).encode()
                self._data.sendall(body)
                self._data.close()
                self._data = None
                self._send(226, "done")
            elif cmd == "SIZE":
                p = self._path(arg)
                if os.path.isfile(p):
                    self._send(213, str(os.path.getsize(p)))
                else:
                    self._send(550, "no file")
            elif cmd == "QUIT":
                self._send(221, "bye")
                break
            else:
                self._send(502, "not implemented")


class _FtpServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, root, users):
        self.root = str(root)
        self.users = users
        super().__init__(("127.0.0.1", 0), _FtpHandler)


@pytest.fixture
def ftp_server(tmp_path):
    root = tmp_path / "ftproot"
    root.mkdir(parents=True, exist_ok=True)
    server = _FtpServer(root, {"tester": "testpwd"})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def test_ftp_uploader_cycle(ftp_server, tmp_path):
    uploader = backup_service.FtpUploader(
        "127.0.0.1", ftp_server, "tester", "testpwd", "/zhy-bk/nested")
    assert "FTP" in uploader.test_connection()

    payload = b"ftp-backup-" * 200
    local = tmp_path / "f.zip"
    local.write_bytes(payload)
    name = "zhy-backup-20260919-010203-mysql.zip"
    uploader.upload(local, name)

    files = uploader.list_files()
    assert len(files) == 1 and files[0]["size"] == len(payload)

    got = tmp_path / "f-download.zip"
    uploader.download(name, got)
    assert got.read_bytes() == payload

    uploader.delete(name)
    assert uploader.list_files() == []


def test_ftp_bad_password(ftp_server):
    bad = backup_service.FtpUploader("127.0.0.1", ftp_server, "tester", "nope", "/zhy-bk")
    with pytest.raises(backup_service.BackupError, match="认证失败"):
        bad.test_connection()


# ---------------------------------------------------------------------------
# 远端备份：成功落地远端 / 失败保留本地包 + failed 记录
# ---------------------------------------------------------------------------

def test_remote_backup_success_and_restore(sftp_server, iso):
    with iso.app_context():
        setting_service.set_raw(setting_service.KEY_BACKUP_TARGET, "remote")
        setting_service.set_raw(setting_service.KEY_BACKUP_PROTOCOL, "sftp")
        setting_service.set_raw(setting_service.KEY_BACKUP_HOST, "127.0.0.1")
        setting_service.set_raw(setting_service.KEY_BACKUP_PORT, str(sftp_server))
        setting_service.set_raw(setting_service.KEY_BACKUP_USERNAME, "tester")
        setting_service.set_raw(setting_service.KEY_BACKUP_PASSWORD_ENC,
                                _encrypt("testpwd"))
        setting_service.set_raw(setting_service.KEY_BACKUP_REMOTE_DIR, "/zhy-bk")

        rec = backup_service.create_backup("manual")
        assert rec.status == "done" and rec.location == "remote"
        assert "sftp://127.0.0.1" in rec.remote_target
        # 本地临时包已删除，远端存在
        assert not (backup_service.backup_dir() / rec.filename).exists()

        items = backup_service.list_backups()
        assert any(i["filename"] == rec.filename and i["exists"] for i in items)

        # 从远端下载恢复
        db.session.query(User).filter_by(username="admin").update({"email": "gone@iso.local"})
        db.session.commit()
        tmp = backup_service.backup_dir() / "dl.zip"
        backup_service.download_remote_file(rec.filename, tmp)
        backup_service.restore_from_package(tmp)
        tmp.unlink()
        db.session.remove()
        assert db.session.query(User).filter_by(
            username="admin").first().email == "admin@iso.local"

        setting_service.set_raw(setting_service.KEY_BACKUP_TARGET, "local")


def _encrypt(raw: str) -> str:
    from flask import current_app

    from app.utils.crypto import encrypt_secret

    return encrypt_secret(raw, current_app.config["SECRET_KEY"])


def test_remote_backup_failure_keeps_local_and_marks_failed(iso):
    with iso.app_context():
        setting_service.set_raw(setting_service.KEY_BACKUP_TARGET, "remote")
        setting_service.set_raw(setting_service.KEY_BACKUP_PROTOCOL, "sftp")
        setting_service.set_raw(setting_service.KEY_BACKUP_HOST, "127.0.0.1")
        setting_service.set_raw(setting_service.KEY_BACKUP_PORT, "1")
        setting_service.set_raw(setting_service.KEY_BACKUP_USERNAME, "u")
        setting_service.set_raw(setting_service.KEY_BACKUP_REMOTE_DIR, "/zhy-bk")

        with pytest.raises(backup_service.BackupError):
            backup_service.create_backup("manual")
        failed = backup_service.BackupRecord.query.filter_by(
            status="failed").order_by(backup_service.BackupRecord.id.desc()).first()
        assert failed is not None and failed.location == "local"
        # 本地包保留
        assert (backup_service.backup_dir() / failed.filename).is_file()

        setting_service.set_raw(setting_service.KEY_BACKUP_TARGET, "local")


# ---------------------------------------------------------------------------
# 备份 API
# ---------------------------------------------------------------------------

def test_backup_api_flow(iso):
    c, headers = _iso_client_headers(iso)

    # 立即备份（后台线程），轮询到 done
    r = c.post("/api/admin/backup", headers=headers)
    assert r.status_code == 200 and r.get_json()["data"]["status"] == "running"

    items = []
    for _ in range(50):
        data = c.get("/api/admin/backups", headers=headers).get_json()["data"]
        items = data["items"]
        if not data["running"]:
            break
        time.sleep(0.1)
    done = [i for i in items if i["status"] == "done" and i["location"] == "local"]
    assert done, items
    bid = done[0]["id"]

    # 下载
    r = c.get(f"/api/admin/backup/download/{bid}", headers=headers)
    assert r.status_code == 200 and r.data[:2] == b"PK"

    # 测试连接：端口不通返回连接错误码
    r = c.post("/api/admin/backup/test-connection", headers=headers, json={
        "backup_protocol": "sftp", "backup_host": "127.0.0.1",
        "backup_port": 1, "backup_username": "u", "backup_password": "p",
        "backup_remote_dir": "/x",
    })
    assert r.status_code == 400 and r.get_json()["code"] == 3603

    # 恢复需确认
    r = c.post("/api/admin/backup/restore", headers=headers, json={"backup_id": bid})
    assert r.status_code == 400 and r.get_json()["code"] == 3607

    # 确认后恢复（拦截进程退出）
    import app.services.backup_service as bs

    bs.schedule_exit = lambda delay=2.0: None
    r = c.post("/api/admin/backup/restore", headers=headers,
               json={"backup_id": bid, "confirm": True})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["data"]["restart_required"] is True

    # 非管理员不可访问
    assert c.post("/api/admin/backup").status_code == 401
