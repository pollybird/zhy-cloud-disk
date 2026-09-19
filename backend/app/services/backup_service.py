"""备份恢复服务（1.3.0）。

备份内容：数据库（MySQL 逻辑导出 / SQLite 在线一致性快照）+ 安装配置，
**不含文件实体**。统一先在本地 storage/backups 打包，再按目标落地：

- local：zip 保留在本地备份目录；
- remote：上传至远端 SFTP（推荐，paramiko）或 FTP（ftplib 被动模式），
  上传成功后删除本地临时包；失败则保留本地包并把记录置 failed。

恢复：校验 manifest 与 sha256 → 先留一份当前库的回滚备份 → 覆盖恢复 →
调用方负责让进程退出由外部守护（supervisor）重新拉起。
"""
import fnmatch
import hashlib
import io
import os
import shutil
import socket
import sqlite3
import subprocess
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from flask import current_app

from ..config import _resolve_instance_dir
from ..extensions import db
from ..models.backup_record import BackupRecord
from . import setting_service

BACKUP_DIRNAME = "backups"
BACKUP_PREFIX = "zhy-backup-"
BACKUP_SUFFIX = ".zip"
MANIFEST_NAME = "manifest.json"
CONFIG_NAME = "config.installed.json"
PROBE_NAME = ".zhy-backup-probe"

CONNECT_TIMEOUT = 30
DUMP_TIMEOUT = 300

# 同一进程内备份串行，避免并发打包/远端竞争
_backup_lock = threading.Lock()


class BackupError(Exception):
    """备份恢复可向管理员展示的错误。"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _backup_filename(db_type: str, now: datetime | None = None) -> str:
    """生成备份文件名；同一秒内连续备份时追加 -2/-3 序号避免冲突。"""
    now = now or _utcnow()
    stamp = now.strftime("%Y%m%d-%H%M%S")

    def _name(seq: int) -> str:
        suffix = f"-{seq}" if seq > 1 else ""
        return f"{BACKUP_PREFIX}{stamp}{suffix}-{db_type}{BACKUP_SUFFIX}"

    candidate = _name(1)
    seq = 2
    while (
        db.session.query(BackupRecord.id).filter_by(filename=candidate).first() is not None
        or (backup_dir() / candidate).exists()
    ):
        candidate = _name(seq)
        seq += 1
    return candidate


def _parse_backup_time(filename: str) -> datetime | None:
    stem = filename
    if stem.startswith(BACKUP_PREFIX):
        stem = stem[len(BACKUP_PREFIX):]
    stem = stem[:15]  # YYYYmmdd-HHMMSS
    try:
        return datetime.strptime(stem, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def backup_dir() -> Path:
    path = Path(current_app.config["STORAGE_DIR"]) / BACKUP_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


# ===========================================================================
# 上传器：本地 / SFTP / FTP，统一接口
# ===========================================================================

class BaseUploader:
    location = "local"

    def test_connection(self) -> str:
        """连通 + 登录 + 目录可写检查；成功返回提示信息，失败抛 BackupError。"""
        raise NotImplementedError

    def upload(self, local_path: Path, filename: str) -> None:
        raise NotImplementedError

    def download(self, filename: str, local_path: Path) -> None:
        raise NotImplementedError

    def list_files(self) -> list[dict]:
        """返回 [{name, size, mtime}]，仅 zip 文件。"""
        raise NotImplementedError

    def delete(self, filename: str) -> None:
        raise NotImplementedError


class LocalUploader(BaseUploader):
    location = "local"

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir

    def _dir(self) -> Path:
        path = self.base_dir or backup_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def test_connection(self) -> str:
        path = self._dir()
        probe = path / PROBE_NAME
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return f"本地备份目录可写：{path}"

    def upload(self, local_path: Path, filename: str) -> None:
        target = self._dir() / filename
        if local_path.resolve() != target.resolve():
            shutil.copy2(local_path, target)

    def download(self, filename: str, local_path: Path) -> None:
        source = self._dir() / filename
        if not source.is_file():
            raise BackupError(f"本地备份不存在：{filename}")
        shutil.copy2(source, local_path)

    def list_files(self) -> list[dict]:
        result = []
        for p in self._dir().glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"):
            if p.is_file():
                result.append({
                    "name": p.name,
                    "size": p.stat().st_size,
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc),
                })
        return result

    def delete(self, filename: str) -> None:
        target = self._dir() / filename
        if target.is_file():
            target.unlink()


class SftpUploader(BaseUploader):
    location = "remote"

    def __init__(self, host: str, port: int, username: str, password: str,
                 remote_dir: str, protocol: str = "sftp"):
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.remote_dir = remote_dir or "/zhy-backups"
        self.protocol = protocol

    def _connect(self):
        try:
            import paramiko
        except ImportError as e:  # pragma: no cover
            raise BackupError("服务器缺少 paramiko 组件，无法使用 SFTP") from e
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=self.host, port=self.port, username=self.username,
                password=self.password, timeout=CONNECT_TIMEOUT,
                banner_timeout=CONNECT_TIMEOUT, auth_timeout=CONNECT_TIMEOUT,
                allow_agent=False, look_for_keys=False,
            )
        except Exception as e:
            raise BackupError(f"SFTP 连接/认证失败：{e}") from e
        return client

    def _ensure_dir(self, sftp, path: str) -> None:
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        cur = ""
        for part in parts:
            cur = f"{cur}/{part}"
            try:
                sftp.stat(cur)
            except IOError:
                try:
                    sftp.mkdir(cur)
                except IOError as e:
                    raise BackupError(f"远端目录创建失败：{cur}（{e}）") from e

    def _open_sftp(self):
        client = self._connect()
        try:
            sftp = client.open_sftp()
        except Exception as e:
            client.close()
            raise BackupError(f"SFTP 通道打开失败：{e}") from e
        return client, sftp

    def test_connection(self) -> str:
        client, sftp = self._open_sftp()
        try:
            self._ensure_dir(sftp, self.remote_dir)
            sftp.chdir(self.remote_dir)
            probe = f"{self.remote_dir.rstrip('/')}/{PROBE_NAME}"
            with sftp.open(probe, "w") as f:
                f.write("ok")
            sftp.remove(probe)
        except BackupError:
            raise
        except Exception as e:
            raise BackupError(f"SFTP 目录不可写：{e}") from e
        finally:
            client.close()
        return f"SFTP 连接成功，目录可写：{self.remote_dir}"

    def upload(self, local_path: Path, filename: str) -> None:
        client, sftp = self._open_sftp()
        try:
            self._ensure_dir(sftp, self.remote_dir)
            sftp.put(str(local_path), f"{self.remote_dir.rstrip('/')}/{filename}")
        except (BackupError, OSError, IOError) as e:
            raise BackupError(f"SFTP 上传失败：{e}") from e
        finally:
            client.close()

    def download(self, filename: str, local_path: Path) -> None:
        client, sftp = self._open_sftp()
        try:
            sftp.get(f"{self.remote_dir.rstrip('/')}/{filename}", str(local_path))
        except Exception as e:
            raise BackupError(f"SFTP 下载失败：{e}") from e
        finally:
            client.close()

    def list_files(self) -> list[dict]:
        client, sftp = self._open_sftp()
        try:
            names = sftp.listdir(self.remote_dir)
            result = []
            for name in names:
                if not (name.startswith(BACKUP_PREFIX) and name.endswith(BACKUP_SUFFIX)):
                    continue
                try:
                    attr = sftp.stat(f"{self.remote_dir.rstrip('/')}/{name}")
                except IOError:
                    continue
                mtime = datetime.fromtimestamp(attr.st_mtime, tz=timezone.utc)
                result.append({"name": name, "size": attr.st_size or 0, "mtime": mtime})
            return result
        except Exception as e:
            raise BackupError(f"SFTP 列目录失败：{e}") from e
        finally:
            client.close()

    def delete(self, filename: str) -> None:
        client, sftp = self._open_sftp()
        try:
            try:
                sftp.remove(f"{self.remote_dir.rstrip('/')}/{filename}")
            except IOError as e:
                if "No such file" not in str(e):
                    raise BackupError(f"SFTP 删除失败：{e}") from e
        finally:
            client.close()

    def target_desc(self, filename: str) -> str:
        return f"{self.protocol}://{self.host}:{self.port}{self.remote_dir.rstrip('/')}/{filename}"


class FtpUploader(BaseUploader):
    location = "remote"

    def __init__(self, host: str, port: int, username: str, password: str,
                 remote_dir: str):
        import ftplib

        self.ftplib = ftplib
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.remote_dir = remote_dir or "/zhy-backups"

    def _connect(self):
        ftp = self.ftplib.FTP()
        try:
            ftp.connect(self.host, self.port, timeout=CONNECT_TIMEOUT)
            ftp.login(self.username or "anonymous", self.password or "")
        except self.ftplib.all_errors as e:
            raise BackupError(f"FTP 连接/认证失败：{e}") from e
        ftp.set_pasv(True)
        return ftp

    def _ensure_dir(self, ftp, path: str) -> None:
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        cur = ""
        for part in parts:
            cur = f"{cur}/{part}"
            try:
                ftp.cwd(cur)
            except self.ftplib.all_errors:
                try:
                    ftp.mkd(cur)
                    ftp.cwd(cur)
                except self.ftplib.all_errors as e:
                    raise BackupError(f"远端目录创建失败：{cur}（{e}）") from e

    def test_connection(self) -> str:
        ftp = self._connect()
        try:
            self._ensure_dir(ftp, self.remote_dir)
            ftp.cwd(self.remote_dir)
            ftp.storbinary(f"STOR {PROBE_NAME}", io.BytesIO(b"ok"))
            try:
                ftp.delete(PROBE_NAME)
            except self.ftplib.all_errors:
                pass
        except BackupError:
            raise
        except self.ftplib.all_errors as e:
            raise BackupError(f"FTP 目录不可写：{e}") from e
        finally:
            ftp.quit()
        return f"FTP 连接成功，目录可写：{self.remote_dir}"

    def upload(self, local_path: Path, filename: str) -> None:
        ftp = self._connect()
        try:
            self._ensure_dir(ftp, self.remote_dir)
            ftp.cwd(self.remote_dir)
            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f, blocksize=65536)
        except BackupError:
            raise
        except self.ftplib.all_errors as e:
            raise BackupError(f"FTP 上传失败：{e}") from e
        finally:
            ftp.quit()

    def download(self, filename: str, local_path: Path) -> None:
        ftp = self._connect()
        try:
            ftp.cwd(self.remote_dir)
            with open(local_path, "wb") as f:
                ftp.retrbinary(f"RETR {filename}", f.write, blocksize=65536)
        except self.ftplib.all_errors as e:
            raise BackupError(f"FTP 下载失败：{e}") from e
        finally:
            ftp.quit()

    def list_files(self) -> list[dict]:
        ftp = self._connect()
        result = []
        try:
            ftp.cwd(self.remote_dir)
            names = ftp.nlst()
            for name in names:
                name = os.path.basename(name)
                if not (name.startswith(BACKUP_PREFIX) and name.endswith(BACKUP_SUFFIX)):
                    continue
                try:
                    size = ftp.size(name) or 0
                except self.ftplib.all_errors:
                    size = 0
                result.append({
                    "name": name,
                    "size": size,
                    "mtime": _parse_backup_time(name) or _utcnow(),
                })
        except self.ftplib.all_errors as e:
            raise BackupError(f"FTP 列目录失败：{e}") from e
        finally:
            ftp.quit()
        return result

    def delete(self, filename: str) -> None:
        ftp = self._connect()
        try:
            ftp.cwd(self.remote_dir)
            try:
                ftp.delete(filename)
            except self.ftplib.all_errors:
                pass
        finally:
            ftp.quit()

    def target_desc(self, filename: str) -> str:
        return f"ftp://{self.host}:{self.port}{self.remote_dir.rstrip('/')}/{filename}"


def build_uploader(config: dict | None = None) -> BaseUploader:
    """按设置构造上传器。target=remote 且缺 host 时报错。"""
    config = config or setting_service.get_backup_remote_config()
    if config.get("target") == "remote":
        host = (config.get("host") or "").strip()
        if not host:
            raise BackupError("尚未配置远端服务器地址")
        if config.get("protocol") == "ftp":
            return FtpUploader(
                host, config.get("port") or 21,
                config.get("username", ""), config.get("password", ""),
                config.get("remote_dir", "/zhy-backups"),
            )
        return SftpUploader(
            host, config.get("port") or 22,
            config.get("username", ""), config.get("password", ""),
            config.get("remote_dir", "/zhy-backups"),
            protocol="sftp",
        )
    return LocalUploader()


def test_remote_config(config: dict) -> str:
    """使用临时配置（测试连接按钮可传入未保存的值）。"""
    merged = setting_service.get_backup_remote_config()
    merged.update({k: v for k, v in config.items() if v is not None and v != ""})
    # 密码：显式传入优先，否则用已保存解密密码
    if config.get("password"):
        merged["password"] = config["password"]
    if not merged.get("host"):
        raise BackupError("请先填写服务器地址")
    uploader = build_uploader(merged)
    return uploader.test_connection()


# ===========================================================================
# 数据库快照 / 恢复
# ===========================================================================

def _db_type() -> str:
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if uri.startswith("sqlite"):
        return "sqlite"
    if uri.startswith("mysql"):
        return "mysql"
    if uri.startswith("postgresql"):
        return "postgresql"
    return "unknown"


def _sqlite_path() -> Path:
    from sqlalchemy.engine import make_url

    url = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
    return Path(url.database)


def _snapshot_sqlite(target: Path) -> None:
    source = _sqlite_path()
    source.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(source))
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _mysql_parts() -> dict:
    from sqlalchemy.engine import make_url

    url = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
    return {
        "host": url.host or "127.0.0.1",
        "port": url.port or 3306,
        "user": url.username or "root",
        "password": url.password or "",
        "database": url.database or "zhycloud",
    }


def _is_docker_socket_mysql(parts: dict) -> bool:
    return (
        parts["user"] == "root"
        and not parts["password"]
        and parts["host"] in ("127.0.0.1", "localhost", "::1")
    )


def _resolve_binary(*names: str) -> str:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    raise BackupError(f"服务器缺少备份工具：{'/'.join(names)}")


def _snapshot_mysql(target: Path) -> None:
    parts = _mysql_parts()
    dump_bin = _resolve_binary("mariadb-dump", "mysqldump")
    cmd = ["--single-transaction", "--add-drop-table", "--routines", "--events"]
    env = dict(os.environ)
    if _is_docker_socket_mysql(parts):
        cmd = [dump_bin, "-u", "root", parts["database"]] + cmd
    else:
        cmd = [
            dump_bin, "-h", parts["host"], "-P", str(parts["port"]),
            "-u", parts["user"], parts["database"],
        ] + cmd
        env["MYSQL_PWD"] = parts["password"]
    try:
        with open(target, "wb") as f:
            proc = subprocess.run(
                cmd, stdout=f, stderr=subprocess.PIPE, env=env,
                timeout=DUMP_TIMEOUT,
            )
    except subprocess.TimeoutExpired as e:
        raise BackupError("数据库导出超时") from e
    except OSError as e:
        raise BackupError(f"数据库导出执行失败：{e}") from e
    if proc.returncode != 0:
        raise BackupError(
            f"数据库导出失败（{proc.returncode}）：{proc.stderr.decode('utf-8', 'ignore')[:300]}"
        )


def _restore_mysql(sql_path: Path) -> None:
    parts = _mysql_parts()
    client_bin = _resolve_binary("mariadb", "mysql")
    env = dict(os.environ)
    if _is_docker_socket_mysql(parts):
        cmd = [client_bin, "-u", "root", parts["database"]]
    else:
        cmd = [
            client_bin, "-h", parts["host"], "-P", str(parts["port"]),
            "-u", parts["user"], parts["database"],
        ]
        env["MYSQL_PWD"] = parts["password"]
    # 导入脚本带 DROP TABLE，必须先释放本进程 SQLAlchemy 连接池：池中开启了
    # 事务的空闲连接会持有表元数据锁（MDL），导致导入客户端自锁等待。
    try:
        db.session.remove()
        db.engine.dispose()
    except Exception:
        pass
    try:
        with open(sql_path, "rb") as f:
            proc = subprocess.run(
                cmd, stdin=f, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, timeout=DUMP_TIMEOUT,
            )
    except subprocess.TimeoutExpired as e:
        raise BackupError("数据库导入超时") from e
    except OSError as e:
        raise BackupError(f"数据库导入执行失败：{e}") from e
    if proc.returncode != 0:
        raise BackupError(
            f"数据库导入失败（{proc.returncode}）：{proc.stderr.decode('utf-8', 'ignore')[:300]}"
        )


def _snapshot_database(target: Path, db_type: str) -> None:
    if db_type == "sqlite":
        _snapshot_sqlite(target)
    elif db_type == "mysql":
        _snapshot_mysql(target)
    else:
        raise BackupError(f"暂不支持 {db_type} 数据库的备份恢复（v1.3.0 仅支持 SQLite/MySQL）")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ===========================================================================
# 打包
# ===========================================================================

def _instance_files() -> list[Path]:
    instance_dir = _resolve_instance_dir()
    if not instance_dir.is_dir():
        return []
    excluded = ("*.db", "*.db-journal", "*.db-wal", "*.db-shm")
    files = []
    for p in instance_dir.iterdir():
        if not p.is_file():
            continue
        if any(fnmatch.fnmatch(p.name, pat) for pat in excluded):
            continue
        if p.name.startswith("pre-restore-"):
            continue
        files.append(p)
    return files


def _assemble_zip(zip_path: Path, db_type: str, db_path: Path) -> None:
    """把数据库快照 + 实例配置打包为 zip，manifest 最后写入。"""
    db_name = db_path.name
    entries: list[tuple[Path, str]] = [(db_path, db_name)]
    hashes = {db_name: _sha256(db_path)}
    for f in _instance_files():
        arc = CONFIG_NAME if f.name == CONFIG_NAME else f"instance/{f.name}"
        entries.append((f, arc))
        hashes[arc] = _sha256(f)

    manifest = {
        "app_version": current_app.config.get("ZHY_VERSION", "unknown"),
        "db_type": db_type,
        "create_time": _utcnow().isoformat(),
        "db_file": db_name,
        "files": hashes,
    }

    tmp_zip = zip_path.parent / f".{zip_path.name}.part"
    tmp_zip.unlink(missing_ok=True)
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, arc in entries:
            zf.write(path, arc)
        zf.writestr(MANIFEST_NAME, _json_dumps(manifest))
    tmp_zip.replace(zip_path)


def _json_dumps(data: dict) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)


# ===========================================================================
# 备份执行 / 记录管理
# ===========================================================================

def is_backup_running() -> bool:
    if _backup_lock.locked():
        return True
    return (
        db.session.query(BackupRecord.id)
        .filter(BackupRecord.status == "running")
        .first()
        is not None
    )


def create_backup(trigger: str = "manual") -> BackupRecord:
    """执行一次备份（调用方负责后台线程与异常兜底）。备份串行。

    顺序：先做数据库快照（此时备份记录行尚未入库，快照不含 running 记录），
    再写 running 记录、打包、上传，最后置 done/failed。
    """
    if not _backup_lock.acquire(blocking=False):
        raise BackupError("已有备份任务正在执行")
    record = None
    work_dir = None
    try:
        db_type = _db_type()
        if db_type == "postgresql":
            raise BackupError("暂不支持 PostgreSQL 数据库的备份恢复（v1.3.0 仅支持 SQLite/MySQL）")
        filename = _backup_filename(db_type)
        local_zip = backup_dir() / filename

        # 1) 数据库快照先于记录行产生
        work_dir = backup_dir() / f".tmp-{local_zip.stem}"
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
        work_dir.mkdir(parents=True)
        db_name = "zhycloud.db" if db_type == "sqlite" else "database.sql"
        db_path = work_dir / db_name
        _snapshot_database(db_path, db_type)

        # 2) 记录 running（不在上面的快照中）
        record = BackupRecord(
            filename=filename, db_type=db_type, trigger=trigger,
            status="running", location="local",
        )
        db.session.add(record)
        db.session.commit()

        # 3) 打包并落地
        _assemble_zip(local_zip, db_type, db_path)

        # 4) 远端上传（失败保留本地包）
        config = setting_service.get_backup_remote_config()
        uploader = build_uploader(config)
        if uploader.location == "remote":
            uploader.upload(local_zip, filename)
            record.location = "remote"
            record.remote_target = uploader.target_desc(filename)
            try:
                local_zip.unlink()
            except OSError:
                pass
        else:
            record.location = "local"
            record.remote_target = None

        record.status = "done"
        record.file_size = local_zip.stat().st_size if local_zip.exists() else (
            _remote_size_safe(uploader, filename)
        )
        record.message = None
        db.session.commit()

        if trigger == "schedule":
            prune_scheduled(setting_service.get_backup_schedule()["keep_count"])
        return record
    except Exception as e:
        db.session.rollback()
        message = str(e) or e.__class__.__name__
        if record is not None and record.id is not None:
            fresh = db.session.get(BackupRecord, record.id)
            if fresh is not None:
                fresh.status = "failed"
                fresh.message = message[:500]
                db.session.commit()
        raise
    finally:
        if work_dir is not None:
            shutil.rmtree(work_dir, ignore_errors=True)
        _backup_lock.release()


def _remote_size_safe(uploader, filename: str) -> int:
    try:
        for item in uploader.list_files():
            if item["name"] == filename:
                return int(item["size"])
    except Exception:
        pass
    return 0


def prune_scheduled(keep_count: int) -> int:
    """按保留份数清理**定时**备份（手动备份不参与），本地/远端均生效。"""
    records = (
        db.session.query(BackupRecord)
        .filter(BackupRecord.trigger == "schedule")
        .all()
    )
    records.sort(key=lambda r: (_parse_backup_time(r.filename) or r.create_time), reverse=True)
    stale = records[keep_count:]
    if not stale:
        return 0
    config = setting_service.get_backup_remote_config()
    removed = 0
    for record in stale:
        uploader = build_uploader(config)
        try:
            uploader.delete(record.filename)
        except BackupError:
            current_app.logger.warning("清理旧备份失败：%s", record.filename, exc_info=True)
        db.session.delete(record)
        removed += 1
    db.session.commit()
    return removed


def list_backups() -> list[dict]:
    """备份记录与存储端实际文件合并：记录标记 exists，游离文件补伪记录。"""
    config = setting_service.get_backup_remote_config()
    uploader = build_uploader(config)
    try:
        fs_files = {item["name"]: item for item in uploader.list_files()}
    except BackupError as e:
        fs_files = {}
        current_app.logger.warning("读取备份存储端失败：%s", e)

    records = db.session.query(BackupRecord).order_by(BackupRecord.id.desc()).all()
    seen = set()
    result = []
    for record in records:
        data = record.to_dict()
        data["exists"] = record.filename in fs_files
        if record.filename in fs_files:
            seen.add(record.filename)
            if not data["file_size"]:
                data["file_size"] = fs_files[record.filename]["size"]
        result.append(data)

    for name, item in fs_files.items():
        if name in seen:
            continue
        ts = _parse_backup_time(name) or item.get("mtime") or _utcnow()
        result.append({
            "id": None,
            "filename": name,
            "file_size": item["size"],
            "db_type": "sqlite" if "-sqlite" in name else ("mysql" if "-mysql" in name else ""),
            "trigger": "manual",
            "status": "done",
            "location": uploader.location,
            "remote_target": None,
            "message": None,
            "create_time": ts.isoformat(),
            "exists": True,
            "orphan": True,
        })
    result.sort(key=lambda x: x["create_time"] or "", reverse=True)
    return result


def get_record(record_id: int) -> BackupRecord:
    record = db.session.get(BackupRecord, int(record_id))
    if record is None:
        raise BackupError("备份记录不存在")
    return record


def local_zip_path(record: BackupRecord) -> Path | None:
    path = backup_dir() / record.filename
    return path if path.is_file() else None


def download_to_temp(record: BackupRecord) -> Path:
    if record.location != "remote":
        path = local_zip_path(record)
        if path is None:
            raise BackupError("本地备份文件已不存在")
        return path
    tmp = backup_dir() / f".dl-{record.filename}"
    build_uploader().download(record.filename, tmp)
    return tmp


def download_remote_file(filename: str, target: Path) -> Path:
    """按文件名从已配置远端目录下载任意备份包（用于恢复游离文件）。"""
    uploader = build_uploader()
    if uploader.location != "remote":
        raise BackupError("当前备份目标不是远端服务器")
    safe_name = os.path.basename(filename)
    uploader.download(safe_name, target)
    return target


def delete_backup(record_id: int) -> None:
    record = get_record(record_id)
    try:
        build_uploader().delete(record.filename)
    except BackupError:
        current_app.logger.warning("删除备份存储端文件失败：%s", record.filename, exc_info=True)
    local_path = backup_dir() / record.filename
    local_path.unlink(missing_ok=True)
    db.session.delete(record)
    db.session.commit()


# ===========================================================================
# 恢复
# ===========================================================================

def _safe_extract(zip_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            dest = (target_dir / member).resolve()
            if not str(dest).startswith(str(target_dir.resolve())):
                raise BackupError(f"备份包含非法路径：{member}")
        zf.extractall(target_dir)


def verify_package(extract_dir: Path) -> dict:
    import json

    manifest_path = extract_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise BackupError("备份包缺少 manifest.json，不是有效的备份文件")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise BackupError(f"manifest.json 解析失败：{e}") from e
    db_file = manifest.get("db_file")
    db_type = manifest.get("db_type")
    if not db_file or db_type not in ("sqlite", "mysql"):
        raise BackupError("manifest 中的数据库信息无效")
    db_path = extract_dir / db_file
    if not db_path.is_file():
        raise BackupError(f"备份包缺少数据库文件：{db_file}")
    expected = (manifest.get("files") or {}).get(db_file)
    if expected and _sha256(db_path) != expected:
        raise BackupError("数据库文件校验失败（sha256 不一致），备份可能已损坏或被篡改")
    return manifest


def _pre_restore_rollback(db_type: str) -> Path | None:
    """恢复前先留一份当前库，放到实例目录 pre-restore-*。"""
    instance_dir = _resolve_instance_dir()
    stamp = _utcnow().strftime("%Y%m%d-%H%M%S")
    try:
        if db_type == "sqlite":
            source = _sqlite_path()
            rollback = instance_dir / f"pre-restore-{stamp}.db"
            con = sqlite3.connect(str(source))
            try:
                dst = sqlite3.connect(str(rollback))
                try:
                    con.backup(dst)
                finally:
                    dst.close()
            finally:
                con.close()
            return rollback
        if db_type == "mysql":
            rollback = instance_dir / f"pre-restore-{stamp}.sql"
            _snapshot_mysql(rollback)
            return rollback
    except BackupError as e:
        current_app.logger.warning("恢复前回滚备份失败（继续恢复）：%s", e)
    return None


def restore_from_package(zip_path: Path) -> dict:
    """从 zip 包恢复数据库与安装配置。返回恢复摘要。"""
    if not zip_path.is_file():
        raise BackupError("备份文件不存在")
    work_dir = backup_dir() / f".restore-{_utcnow().strftime('%Y%m%d%H%M%S%f')}"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        _safe_extract(zip_path, work_dir)
        manifest = verify_package(work_dir)
        db_type = manifest["db_type"]
        current_type = _db_type()
        if db_type != current_type:
            raise BackupError(
                f"备份数据库类型（{db_type}）与当前系统（{current_type}）不一致，无法恢复"
            )

        rollback = _pre_restore_rollback(db_type)

        if db_type == "sqlite":
            db_path = work_dir / manifest["db_file"]
            _restore_sqlite(db_path)
        else:
            _restore_mysql(work_dir / manifest["db_file"])

        _restore_installed_config(work_dir)

        # 数据库已整体回滚到备份时点，清除 Redis 中基于旧库构建的缓存，
        # 否则恢复后的设置值 / 插件启停状态会被旧缓存覆盖。
        try:
            from .cache_service import cache_flush_pattern

            cache_flush_pattern("setting:*")
            cache_flush_pattern("plugin:*")
            cache_flush_pattern("jwt:revoked:*")
        except Exception:
            current_app.logger.warning("恢复后清理缓存失败，重启后将自然失效", exc_info=True)

        return {
            "db_type": db_type,
            "app_version": manifest.get("app_version"),
            "backup_time": manifest.get("create_time"),
            "rollback_file": str(rollback) if rollback else None,
            "restart_required": True,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _restore_sqlite(snapshot_path: Path) -> None:
    target = _sqlite_path()
    # 关闭连接池，避免覆盖后旧连接持有已失效文件句柄
    try:
        db.engine.dispose()
    except Exception:
        pass
    # 快照内容已含全部已提交页；清理目标库残留的 WAL/SHM
    for suffix in ("-wal", "-shm", "-journal"):
        p = target.with_name(target.name + suffix)
        p.unlink(missing_ok=True)
    shutil.copy2(snapshot_path, target)
    # 校验可读
    check = sqlite3.connect(str(target))
    try:
        check.execute("PRAGMA integrity_check").fetchone()
    finally:
        check.close()


def _restore_installed_config(extract_dir: Path) -> None:
    """恢复安装配置（仅当包内携带且与当前不同）。"""
    import json

    src = extract_dir / CONFIG_NAME
    if not src.is_file():
        return
    try:
        payload = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict) or "database_uri" not in payload:
        return
    target = _resolve_instance_dir() / CONFIG_NAME
    current = {}
    if target.is_file():
        try:
            current = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    if current != payload:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def schedule_exit(delay: float = 2.0) -> None:
    """恢复成功后退出进程，交由 supervisor / 部署方重启。测试可 monkeypatch。"""
    def _exit():
        os._exit(0)

    timer = threading.Timer(delay, _exit)
    timer.daemon = True
    timer.start()
