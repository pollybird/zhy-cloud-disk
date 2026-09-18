"""APScheduler 调度入口：注册周期任务。

单进程部署由后台调度器负责；多进程场景下数据库条件更新（cleanup_expired）
本身具备幂等兜底能力，多个执行体同时运行也不会出错。
"""
from ..extensions import scheduler
from . import blob_adopt, lock_cleanup, share_cleanup, upload_cleanup

_JOB_ID = "share-cleanup"
_TRIGGER_INTERVAL_MINUTES = 10

_UPLOAD_JOB_ID = "upload-cleanup"
_UPLOAD_INTERVAL_MINUTES = 10

_ADOPT_JOB_ID = "blob-adopt"
_ADOPT_INTERVAL_HOURS = 24

_LOCK_JOB_ID = "lock-cleanup"
_LOCK_INTERVAL_MINUTES = 5


def start_scheduler(app) -> None:
    """启动调度器并注册后台任务（幂等，可重复调用）。"""
    if scheduler.get_job(_JOB_ID) is None:
        scheduler.add_job(
            func=lambda: _run_with_context(app, share_cleanup.run),
            trigger="interval",
            minutes=_TRIGGER_INTERVAL_MINUTES,
            id=_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    if scheduler.get_job(_UPLOAD_JOB_ID) is None:
        scheduler.add_job(
            func=lambda: _run_with_context(app, upload_cleanup.run),
            trigger="interval",
            minutes=_UPLOAD_INTERVAL_MINUTES,
            id=_UPLOAD_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    if scheduler.get_job(_ADOPT_JOB_ID) is None:
        scheduler.add_job(
            func=lambda: _run_with_context(app, blob_adopt.run),
            trigger="interval",
            hours=_ADOPT_INTERVAL_HOURS,
            id=_ADOPT_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    if scheduler.get_job(_LOCK_JOB_ID) is None:
        scheduler.add_job(
            func=lambda: _run_with_context(app, lock_cleanup.run),
            trigger="interval",
            minutes=_LOCK_INTERVAL_MINUTES,
            id=_LOCK_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    if not scheduler.running:
        scheduler.start()


def _run_with_context(app, task_fn) -> None:
    with app.app_context():
        task_fn()
