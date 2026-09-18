"""过期排他编辑锁清理（1.2.0）。

客户端崩溃/断网无法显式释放时，锁记录依赖 TTL（2 分钟）失效；
本任务周期物理删除过期行，保持 file_lock 表干净。
"""
from ..services import file_lock_service


def run() -> dict:
    """执行一轮清理，返回 {expired_locks: 删除条数}。"""
    return {"expired_locks": file_lock_service.purge_expired()}
