"""监控指标采集（1.3.0）。

- CPU/内存：psutil 为主，Linux 容器内按 cgroup v2/v1 限额修正（容器看到的
  /proc 是宿主机指标，必须以 cgroup 限额为准）。
- 磁盘：shutil.disk_usage(存储根目录)。
- 在线人数：User.last_active_time 在近 5 分钟内的用户数；after_request 钩子
  每用户 60 秒最多回写一次。
- 流量：after_request 钩子按上传/下载请求累计，先在进程内聚合，每 10 秒批量
  落库到 SystemSetting（键 traffic_up:YYYYMMDD / traffic_down:YYYYMMDD），
  保留 30 天。多 worker 下各进程分别聚合，最终一致。
"""
import os
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import current_app

from ..extensions import db
from ..models.department import Department
from ..models.file_node import FileNode
from ..models.system_setting import SystemSetting
from ..models.user import User
from .cache_service import cache_exists, cache_get, cache_set

ONLINE_WINDOW_SECONDS = 5 * 60
ACTIVE_THROTTLE_SECONDS = 60
TRAFFIC_FLUSH_SECONDS = 10
TRAFFIC_KEEP_DAYS = 30

_CPU_CACHE_KEY = "metrics:cpu-sample"
_ACTIVE_CACHE_PREFIX = "metrics:active:"

_CGROUP_V2_ROOT = "/sys/fs/cgroup"
_CGROUP_V1_MEMORY = "/sys/fs/cgroup/memory"
_CGROUP_V1_CPU = "/sys/fs/cgroup/cpu"
_CGROUP_V1_CPUACCT = "/sys/fs/cgroup/cpuacct"

# 进程内流量聚合
_pending_traffic: dict[str, dict[str, int]] = {}
_traffic_lock = threading.Lock()
_last_flush_ts = 0.0

# cgroup CPU 增量采样状态
_cpu_sample_lock = threading.Lock()
_last_cgroup_cpu: tuple[int, float] | None = None  # (usage_ns, wall_ts)

try:
    import psutil
except ImportError:  # pragma: no cover - requirements 已固定
    psutil = None

if psutil is not None:
    try:
        psutil.cpu_percent(interval=None)  # 启动计数器基线
    except Exception:
        pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _day_key(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# cgroup 读取（纯函数解析，便于单测）
# ---------------------------------------------------------------------------

def _read_text(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _parse_cgroup_v2_memory() -> tuple[int | None, int | None]:
    """返回 (limit, usage) 字节；非 cgroup v2 限额环境返回 (None, None)。"""
    max_raw = _read_text(os.path.join(_CGROUP_V2_ROOT, "memory.max"))
    cur_raw = _read_text(os.path.join(_CGROUP_V2_ROOT, "memory.current"))
    if max_raw is None or cur_raw is None:
        return None, None
    max_raw = max_raw.strip()
    if max_raw == "max":
        return None, int(cur_raw)
    try:
        return int(max_raw), int(cur_raw)
    except ValueError:
        return None, None


def _parse_cgroup_v1_memory() -> tuple[int | None, int | None]:
    limit_raw = _read_text(os.path.join(_CGROUP_V1_MEMORY, "memory.limit_in_bytes"))
    usage_raw = _read_text(os.path.join(_CGROUP_V1_MEMORY, "memory.usage_in_bytes"))
    stat_raw = _read_text(os.path.join(_CGROUP_V1_MEMORY, "memory.stat"))
    if limit_raw is None or usage_raw is None:
        return None, None
    try:
        limit = int(limit_raw.strip())
        usage = int(usage_raw.strip())
    except ValueError:
        return None, None
    # usage 含 page cache，扣除 inactive_file 更接近真实占用
    if stat_raw:
        for line in stat_raw.splitlines():
            if line.startswith("total_inactive_file ") or line.startswith("inactive_file "):
                try:
                    usage = max(usage - int(line.split()[1]), 0)
                except (IndexError, ValueError):
                    pass
                break
    # 未限额时值为 2^63-1 附近的哨兵
    if limit >= 2 ** 62:
        return None, usage
    return limit, usage


def memory_usage() -> dict:
    """内存指标，容器限额优先。"""
    limit, used = _parse_cgroup_v2_memory()
    cgroup = limit is not None
    if limit is None:
        limit, used = _parse_cgroup_v1_memory()
        cgroup = limit is not None

    if limit is not None and used is not None:
        return {
            "total": limit,
            "used": used,
            "available": max(limit - used, 0),
            "percent": round(used * 100.0 / limit, 1),
            "cgroup": True,
        }

    if psutil is not None:
        vm = psutil.virtual_memory()
        return {
            "total": vm.total,
            "used": vm.used,
            "available": vm.available,
            "percent": round(vm.percent, 1),
            "cgroup": False,
        }
    return {"total": 0, "used": 0, "available": 0, "percent": 0.0, "cgroup": False}


def _parse_cpu_quota_v2() -> float | None:
    """cpu.max：'quota period'（微秒）或 'max'。返回限额核数。"""
    raw = _read_text(os.path.join(_CGROUP_V2_ROOT, "cpu.max"))
    if not raw:
        return None
    parts = raw.split()
    if parts[0] == "max" or len(parts) < 2:
        return None
    try:
        return int(parts[0]) / int(parts[1])
    except ValueError:
        return None


def _parse_cpu_quota_v1() -> float | None:
    quota_raw = _read_text(os.path.join(_CGROUP_V1_CPU, "cpu.cfs_quota_us"))
    period_raw = _read_text(os.path.join(_CGROUP_V1_CPU, "cpu.cfs_period_us"))
    if not quota_raw or not period_raw:
        return None
    try:
        quota = int(quota_raw.strip())
        if quota <= 0:
            return None
        return quota / int(period_raw.strip())
    except ValueError:
        return None


def _read_cgroup_cpu_usage_ns() -> int | None:
    # v2: cpu.stat 中 usage_usec（微秒）
    stat = _read_text(os.path.join(_CGROUP_V2_ROOT, "cpu.stat"))
    if stat:
        for line in stat.splitlines():
            if line.startswith("usage_usec "):
                try:
                    return int(line.split()[1]) * 1000
                except (IndexError, ValueError):
                    return None
    # v1: cpuacct.usage（纳秒）
    raw = _read_text(os.path.join(_CGROUP_V1_CPUACCT, "cpuacct.usage"))
    if raw:
        try:
            return int(raw.strip())
        except ValueError:
            return None
    return None


def cpu_quota() -> float | None:
    return _parse_cpu_quota_v2() or _parse_cpu_quota_v1()


def sample_cpu() -> dict:
    """计算一次 CPU 使用率，结果缓存供仪表盘读取（调度器每 15 秒调用）。

    cgroup 限额环境：按 cgroup CPU 使用增量 / (限额核数 × 墙钟增量) 计算；
    首次采样无增量数据时回退 psutil 主机口径。
    """
    global _last_cgroup_cpu

    cores = os.cpu_count() or 1
    quota = cpu_quota()
    limited = quota is not None
    effective_cores = quota if limited else cores
    percent: float | None = None

    usage_ns = _read_cgroup_cpu_usage_ns() if limited else None
    if limited and usage_ns is not None:
        now_wall = time.monotonic()
        with _cpu_sample_lock:
            prev = _last_cgroup_cpu
            _last_cgroup_cpu = (usage_ns, now_wall)
        if prev is not None:
            prev_usage, prev_wall = prev
            d_usage = usage_ns - prev_usage
            d_wall = now_wall - prev_wall
            if d_wall > 0:
                percent = min(d_usage / (effective_cores * d_wall * 1e9) * 100.0, 100.0)

    if percent is None and psutil is not None:
        percent = psutil.cpu_percent(interval=None)

    sample = {
        "percent": round(percent or 0.0, 1),
        "cores": cores,
        "quota_cores": round(effective_cores, 2),
        "limited": limited,
        "sampled_at": _utcnow().isoformat(),
    }
    cache_set(_CPU_CACHE_KEY, sample, ttl=90)
    return sample


def cpu_usage() -> dict:
    sample = cache_get(_CPU_CACHE_KEY)
    if not sample:
        sample = sample_cpu()
    return sample


# ---------------------------------------------------------------------------
# 磁盘
# ---------------------------------------------------------------------------

def disk_usage() -> dict:
    path = current_app.config["STORAGE_DIR"]
    usage = shutil.disk_usage(path)
    return {
        "path": path,
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": round(usage.used * 100.0 / usage.total, 1) if usage.total else 0.0,
    }


# ---------------------------------------------------------------------------
# 在线人数（after_request 节流回写）
# ---------------------------------------------------------------------------

def touch_active(user) -> None:
    """更新用户活跃时间；每用户 60 秒最多落库一次。"""
    cache_key = f"{_ACTIVE_CACHE_PREFIX}{user.id}"
    if cache_exists(cache_key):
        return
    now = _utcnow()
    db.session.query(User).filter(User.id == user.id).update(
        {User.last_active_time: now}, synchronize_session=False
    )
    db.session.commit()
    cache_set(cache_key, 1, ttl=ACTIVE_THROTTLE_SECONDS)
    user.last_active_time = now


def online_user_count() -> int:
    cutoff = _utcnow() - timedelta(seconds=ONLINE_WINDOW_SECONDS)
    return (
        db.session.query(db.func.count(User.id))
        .filter(User.status == "active", User.last_active_time >= cutoff)
        .scalar()
        or 0
    )


# ---------------------------------------------------------------------------
# 流量统计
# ---------------------------------------------------------------------------

def _traffic_key(direction: str, day: str) -> str:
    return f"traffic_{direction}:{day}"


def record_traffic(up: int = 0, down: int = 0) -> None:
    """累计流量字节数；进程内聚合，按周期批量落库。"""
    global _last_flush_ts
    if up <= 0 and down <= 0:
        return
    day = _day_key(_utcnow())
    with _traffic_lock:
        bucket = _pending_traffic.setdefault(day, {"up": 0, "down": 0})
        bucket["up"] += max(int(up), 0)
        bucket["down"] += max(int(down), 0)
        due = (time.monotonic() - _last_flush_ts) >= TRAFFIC_FLUSH_SECONDS
    if due:
        flush_traffic()


def flush_traffic() -> None:
    """把进程内累计的流量写入数据库（读-改-写），并清理超期数据。"""
    global _last_flush_ts
    with _traffic_lock:
        if not _pending_traffic:
            _last_flush_ts = time.monotonic()
            return
        pending = {d: dict(v) for d, v in _pending_traffic.items()}
        _pending_traffic.clear()
        _last_flush_ts = time.monotonic()

    try:
        for day, delta in pending.items():
            for direction, value in delta.items():
                if value <= 0:
                    continue
                key = _traffic_key(direction, day)
                row = db.session.get(SystemSetting, key)
                if row is None:
                    db.session.add(SystemSetting(key=key, value=str(value)))
                else:
                    row.value = str(max(int(row.value or 0) + value, 0))
        _purge_old_traffic()
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        # 落库失败：合并回待写缓冲，下个周期重试
        with _traffic_lock:
            for day, delta in pending.items():
                bucket = _pending_traffic.setdefault(day, {"up": 0, "down": 0})
                bucket["up"] += delta["up"]
                bucket["down"] += delta["down"]
        try:
            current_app.logger.debug("流量指标落库失败，已缓冲到下个周期", exc_info=True)
        except Exception:
            pass


def _purge_old_traffic() -> None:
    cutoff = _day_key(_utcnow() - timedelta(days=TRAFFIC_KEEP_DAYS))
    # 下划线在 LIKE 中是通配符，显式转义
    rows = (
        db.session.query(SystemSetting)
        .filter(SystemSetting.key.like("traffic\\_%", escape="\\"))
        .all()
    )
    for row in rows:
        day = row.key.rsplit(":", 1)[-1]
        if day < cutoff:
            db.session.delete(row)


def traffic_stats(days: int = 7) -> dict:
    """返回今日上/下行与近 N 天明细（含今天，按日期升序）。"""
    today = _utcnow().date()
    detail = []
    today_up = today_down = 0
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        day = d.strftime("%Y%m%d")
        up = _read_traffic_value("up", day)
        down = _read_traffic_value("down", day)
        # 叠加进程内尚未落库的部分
        with _traffic_lock:
            pending = _pending_traffic.get(day)
            if pending:
                up += pending["up"]
                down += pending["down"]
        detail.append({"date": d.isoformat(), "up": up, "down": down})
        if i == 0:
            today_up, today_down = up, down
    return {"today_up": today_up, "today_down": today_down, "days": detail}


def _read_traffic_value(direction: str, day: str) -> int:
    row = db.session.get(SystemSetting, _traffic_key(direction, day))
    try:
        return int(row.value) if row else 0
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# 存储与用户统计
# ---------------------------------------------------------------------------

def storage_stats() -> dict:
    user_used = db.session.query(
        db.func.coalesce(db.func.sum(User.used_storage), 0)
    ).scalar() or 0
    dept_used = db.session.query(
        db.func.coalesce(db.func.sum(Department.used_storage), 0)
    ).scalar() or 0
    quota_total = db.session.query(
        db.func.coalesce(db.func.sum(User.total_storage), 0)
    ).scalar() or 0
    user_count = db.session.query(db.func.count(User.id)).scalar() or 0
    dept_count = db.session.query(db.func.count(Department.id)).scalar() or 0
    file_count = (
        db.session.query(db.func.count(FileNode.id))
        .filter(FileNode.is_folder.is_(False), FileNode.status == "normal")
        .scalar()
        or 0
    )
    folder_count = (
        db.session.query(db.func.count(FileNode.id))
        .filter(FileNode.is_folder.is_(True), FileNode.status == "normal")
        .scalar()
        or 0
    )
    return {
        "used": int(user_used) + int(dept_used),
        "personal_used": int(user_used),
        "department_used": int(dept_used),
        "quota_total": int(quota_total),
        "user_count": int(user_count),
        "department_count": int(dept_count),
        "file_count": int(file_count),
        "folder_count": int(folder_count),
    }


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------

def get_metrics() -> dict:
    return {
        "cpu": cpu_usage(),
        "memory": memory_usage(),
        "disk": disk_usage(),
        "online_users": online_user_count(),
        "traffic": traffic_stats(),
        "storage": storage_stats(),
        "generated_at": _utcnow().isoformat(),
    }
