"""过期分享清理任务。"""
from ..extensions import db  # noqa: F401  确保应用上下文内可用
from ..services.share_service import cleanup_expired


def run() -> int:
    """把到期分享置为 expired，返回处理条数。"""
    return cleanup_expired()
