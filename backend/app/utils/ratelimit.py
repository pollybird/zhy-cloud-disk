"""轻量限频：基于缓存原子计数；无 Redis 时回退进程内计数（单 worker 有效）。"""
from flask import request

from ..services.cache_service import cache_incr
from .errors import ApiError


def client_ip() -> str:
    """取客户端 IP。

    可信部署形态：nginx 以覆盖方式设置 X-Forwarded-For，后端经 ProxyFix
    （wsgi.py，x_for=1）处理；直连场景取 remote_addr。
    """
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def rate_limit(scope: str, limit: int, window: int, key_extra: str = "") -> None:
    """同一 (scope, IP, key_extra) 在 window 秒内超过 limit 次则拒绝（429）。

    例：rate_limit("login", limit=5, window=60, key_extra=username)
    """
    key = f"rl:{scope}:{client_ip()}:{key_extra}"
    count = cache_incr(key, ttl=window)
    if count > limit:
        raise ApiError("操作过于频繁，请稍后再试", code=4290, http_status=429)
