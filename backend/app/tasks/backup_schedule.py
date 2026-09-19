"""定时备份任务：调度器每小时 :17 唤醒一次，仅在设置的 backup_hour 点执行
（设置变更无需重启即可生效；备份开关关闭时跳过）。"""
from datetime import datetime

from ..services import backup_service, setting_service


def run() -> dict:
    if not setting_service.is_backup_enabled():
        return {"skipped": True, "reason": "backup_disabled"}
    cfg = setting_service.get_backup_config()
    if datetime.now().hour != int(cfg.get("hour", setting_service.DEFAULT_BACKUP_HOUR)):
        return {"skipped": True, "reason": "hour_not_matched"}
    record = backup_service.create_backup("schedule")
    return {"filename": record.filename, "status": record.status, "location": record.location}
