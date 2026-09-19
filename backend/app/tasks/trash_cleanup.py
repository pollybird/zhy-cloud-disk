"""定时任务：彻底清理超过保留期的回收站条目（每小时）。"""
from ..services import trash_service


def run() -> dict:
    result = trash_service.purge_expired()
    return {"purged": result["count"], "freed_bytes": result["freed"]}
