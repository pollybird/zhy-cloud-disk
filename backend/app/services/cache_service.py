"""缓存服务：Redis 优先，无 Redis 时回退到进程内内存缓存。

适用场景：系统设置缓存、分享密码限频、JWT 吊销列表、插件状态缓存。
Redis 不可用时不影响核心功能，降级为单进程内存缓存（多 worker 下限频与吊销可能不完全一致）。
"""
import json
import threading
import time
from typing import Any

# Redis 客户端单例（在 init_cache 中初始化）
_redis_client = None
_redis_checked = False

# 内存回退缓存：key -> (value, expire_at 或 0 表示不过期)
_memory_cache: dict[str, tuple[Any, float]] = {}
_memory_lock = threading.Lock()

# 缓存键前缀
_PREFIX = "zhy:"


def _key(key: str) -> str:
    return f"{_PREFIX}{key}"


def init_cache(app) -> None:
    """在应用工厂中调用：尝试连接 Redis，失败则降级内存缓存。"""
    global _redis_client, _redis_checked
    _redis_checked = True
    url = app.config.get("REDIS_URL")
    if not url:
        _redis_client = None
        app.logger.info("未配置 Redis，使用内存缓存")
        return
    try:
        import redis

        _redis_client = redis.Redis.from_url(
            url, decode_responses=True,
            socket_timeout=2, socket_connect_timeout=2,
        )
        _redis_client.ping()
        app.logger.info("Redis 连接成功：%s", _redis_client.connection_pool.connection_kwargs.get("host", "redis"))
    except ImportError:
        _redis_client = None
        app.logger.warning("redis 包未安装，降级为内存缓存")
    except Exception as e:
        _redis_client = None
        app.logger.warning("Redis 连接失败（%s），降级为内存缓存", e)


def is_redis_available() -> bool:
    return _redis_client is not None


# ---------------------------------------------------------------------------
# 基本缓存操作
# ---------------------------------------------------------------------------

def cache_get(key: str, default: Any = None) -> Any:
    """获取缓存值；Redis 不可用时回退内存。"""
    if _redis_client is not None:
        val = _redis_client.get(_key(key))
        if val is None:
            return default
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    # 内存回退
    with _memory_lock:
        item = _memory_cache.get(_key(key))
        if item is None:
            return default
        value, expire_at = item
        if expire_at and time.monotonic() > expire_at:
            _memory_cache.pop(_key(key), None)
            return default
        return value


def cache_set(key: str, value: Any, ttl: int = 0) -> None:
    """设置缓存；ttl 秒，0 表示不过期。"""
    if _redis_client is not None:
        serialized = json.dumps(value, ensure_ascii=False)
        if ttl > 0:
            _redis_client.setex(_key(key), ttl, serialized)
        else:
            _redis_client.set(_key(key), serialized)
        return
    with _memory_lock:
        expire_at = time.monotonic() + ttl if ttl > 0 else 0
        _memory_cache[_key(key)] = (value, expire_at)


def cache_delete(key: str) -> None:
    if _redis_client is not None:
        _redis_client.delete(_key(key))
        return
    with _memory_lock:
        _memory_cache.pop(_key(key), None)


def cache_exists(key: str) -> bool:
    if _redis_client is not None:
        return _redis_client.exists(_key(key)) > 0
    with _memory_lock:
        item = _memory_cache.get(_key(key))
        if item is None:
            return False
        if item[1] and time.monotonic() > item[1]:
            _memory_cache.pop(_key(key), None)
            return False
        return True


# ---------------------------------------------------------------------------
# 高级操作
# ---------------------------------------------------------------------------

def cache_incr(key: str, ttl: int = 60) -> int:
    """原子递增并设置 TTL；返回递增后的值。

    用于限频：每次尝试 INCR，首次设置过期时间，超过阈值即拒绝。
    """
    if _redis_client is not None:
        pipe = _redis_client.pipeline()
        pipe.incr(_key(key))
        pipe.expire(_key(key), ttl)
        results = pipe.execute()
        return results[0]
    # 内存回退：非原子但单进程可用
    with _memory_lock:
        k = _key(key)
        item = _memory_cache.get(k)
        now = time.monotonic()
        if item is None or (item[1] and now > item[1]):
            _memory_cache[k] = (1, now + ttl)
            return 1
        count = item[0] + 1
        _memory_cache[k] = (count, item[1])
        return count


def cache_ttl(key: str) -> int:
    """返回剩余 TTL 秒数；不存在或不过期返回 -1。"""
    if _redis_client is not None:
        return _redis_client.ttl(_key(key))
    with _memory_lock:
        item = _memory_cache.get(_key(key))
        if item is None:
            return -1
        if not item[1]:
            return -1
        remaining = item[1] - time.monotonic()
        return max(int(remaining), 0)


def cache_flush_pattern(pattern: str) -> int:
    """按通配符删除缓存键；返回删除数量。"""
    if _redis_client is not None:
        full_pattern = _key(pattern)
        count = 0
        for key in _redis_client.scan_iter(full_pattern, count=100):
            _redis_client.delete(key)
            count += 1
        return count
    with _memory_lock:
        import fnmatch

        full_pattern = _key(pattern)
        keys_to_delete = [k for k in _memory_cache if fnmatch.fnmatch(k, full_pattern)]
        for k in keys_to_delete:
            del _memory_cache[k]
        return len(keys_to_delete)
