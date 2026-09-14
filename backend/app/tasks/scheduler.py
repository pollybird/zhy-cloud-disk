"""APScheduler 调度入口：注册周期任务。

单进程部署由后台调度器负责；多进程场景下数据库条件更新（cleanup_expired）
本身具备幂等兜底能力，多个执行体同时运行也不会出错。
"""
from ..extensions import scheduler

_JOB_ID = "share-cleanup"
_TRIGGER_INTERVAL_MINUTES = 10


def start_scheduler(app) -> None:
    """启动调度器并注册分享清理任务（幂等，可重复调用）。"""
    from . import share_cleanup

    if scheduler.get_job(_JOB_ID) is None:
        scheduler.add_job(
            func=lambda: _run_with_context(app),
            trigger="interval",
            minutes=_TRIGGER_INTERVAL_MINUTES,
            id=_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    if not scheduler.running:
        scheduler.start()


def _run_with_context(app) -> None:
    with app.app_context():
        share_cleanup.run()
