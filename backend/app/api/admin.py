"""管理员接口：监控仪表盘、备份恢复（1.3.0）。"""
import threading
from datetime import datetime, timezone

from flask import Blueprint, after_this_request, current_app, request, send_file

from ..services import backup_service, metrics_service
from ..utils.decorators import admin_required
from ..utils.errors import ApiError
from ..utils.response import success

bp = Blueprint("admin", __name__, url_prefix="/api/admin")

# 备份相关错误码
CODE_BUSY = 3601
CODE_FAILED = 3602
CODE_CONN = 3603
CODE_NOT_FOUND = 3604
CODE_BAD_PACKAGE = 3605
CODE_UNSUPPORTED = 3606
CODE_CONFIRM = 3607


def _api_backup_error(e: Exception) -> ApiError:
    message = str(e)
    code = CODE_FAILED
    http_status = 400
    if "不存在" in message or "未找到" in message:
        code, http_status = CODE_NOT_FOUND, 404
    elif "连接" in message or "认证失败" in message or "登录" in message:
        code = CODE_CONN
    elif "manifest" in message or "校验失败" in message or "非法" in message or "无效" in message:
        code = CODE_BAD_PACKAGE
    elif "暂不支持" in message:
        code, http_status = CODE_UNSUPPORTED, 400
    return ApiError(message, code=code, http_status=http_status)


@bp.get("/metrics")
@admin_required
def admin_metrics():
    """监控仪表盘指标：CPU/内存/磁盘/在线人数/流量/存储。"""
    return success(metrics_service.get_metrics())


# ---------------------------------------------------------------------------
# 备份恢复
# ---------------------------------------------------------------------------

def _run_backup_in_thread(trigger: str) -> None:
    app = current_app._get_current_object()

    def runner():
        with app.app_context():
            try:
                backup_service.create_backup(trigger)
            except backup_service.BackupError:
                app.logger.warning("备份任务失败", exc_info=True)
            except Exception:
                app.logger.exception("备份任务异常")

    threading.Thread(target=runner, daemon=True).start()


@bp.post("/backup")
@admin_required
def admin_start_backup():
    """立即执行一次备份，按当前备份目标（本地/远端）落地，后台执行。"""
    if backup_service.is_backup_running():
        raise ApiError("已有备份任务正在执行，请稍后再试", code=CODE_BUSY, http_status=409)
    _run_backup_in_thread("manual")
    return success({"status": "running"}, msg="备份已在后台开始，可刷新列表查看进度")


@bp.post("/backup/test-connection")
@admin_required
def admin_test_backup_connection():
    """测试远端 SFTP/FTP 连通性、登录与目录可写；不产生备份。"""
    payload = request.get_json(silent=True) or {}
    config = {
        "target": "remote",
        "protocol": payload.get("backup_protocol"),
        "host": payload.get("backup_host"),
        "port": payload.get("backup_port"),
        "username": payload.get("backup_username"),
        "password": payload.get("backup_password"),
        "remote_dir": payload.get("backup_remote_dir"),
    }
    try:
        message = backup_service.test_remote_config(config)
    except backup_service.BackupError as e:
        raise _api_backup_error(e) from e
    return success({"ok": True}, msg=message)


@bp.get("/backups")
@admin_required
def admin_list_backups():
    """备份列表（备份记录与本地/远端存储端实际文件合并）。"""
    try:
        items = backup_service.list_backups()
    except backup_service.BackupError as e:
        raise _api_backup_error(e) from e
    return success({"items": items, "running": backup_service.is_backup_running()})


@bp.get("/backup/download/<int:record_id>")
@admin_required
def admin_download_backup(record_id: int):
    """下载备份 zip；远端记录先由服务端拉取。"""
    try:
        record = backup_service.get_record(record_id)
        path = backup_service.download_to_temp(record)
    except backup_service.BackupError as e:
        raise _api_backup_error(e) from e
    if record.location == "remote":
        @after_this_request
        def _remove_temp(response):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return response
    return send_file(
        str(path), as_attachment=True, download_name=record.filename,
        mimetype="application/zip",
    )


@bp.delete("/backup/<int:record_id>")
@admin_required
def admin_delete_backup(record_id: int):
    """删除备份（本地文件/远端文件 + 记录）。"""
    try:
        backup_service.delete_backup(record_id)
    except backup_service.BackupError as e:
        raise _api_backup_error(e) from e
    return success(msg="备份已删除")


@bp.post("/backup/restore")
@admin_required
def admin_restore_backup():
    """从上传 zip / 服务器记录 / 远端文件名恢复。必须 confirm=true。

    成功后 2 秒进程退出，由部署守护（Docker supervisor）自动拉起。
    """
    confirm = request.form.get("confirm") if request.content_type and "multipart" in request.content_type else None
    payload = request.get_json(silent=True) or {}
    if confirm is None:
        confirm = request.form.get("confirm") or payload.get("confirm")
    if confirm is not True and str(confirm).lower() != "true":
        raise ApiError(
            "恢复会覆盖当前数据库，请明确勾选确认后再执行",
            code=CODE_CONFIRM, http_status=400,
        )

    ephemeral_path = None
    try:
        uploaded = request.files.get("file") if request.content_type and "multipart" in request.content_type else None
        backup_id = request.form.get("backup_id") if uploaded is not None else payload.get("backup_id")
        remote_filename = (
            request.form.get("remote_filename") if uploaded is not None
            else payload.get("remote_filename")
        )

        if uploaded is not None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
            ephemeral_path = backup_service.backup_dir() / f".restore-upload-{stamp}.zip"
            uploaded.save(str(ephemeral_path))
            zip_path = ephemeral_path
        elif backup_id:
            record = backup_service.get_record(int(backup_id))
            zip_path = backup_service.download_to_temp(record)
            if record.location == "remote":
                ephemeral_path = zip_path
        elif remote_filename:
            # 恢复后旧备份会成为本地游离文件（记录已随旧库消失），优先在本地
            # 备份目录按文件名查找，找不到再按远端文件下载。
            from pathlib import Path

            safe_name = Path(str(remote_filename)).name
            local_candidate = backup_service.backup_dir() / safe_name
            if (
                safe_name.startswith("zhy-backup-")
                and safe_name.endswith(".zip")
                and local_candidate.is_file()
            ):
                zip_path = local_candidate
            else:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
                ephemeral_path = backup_service.backup_dir() / f".restore-remote-{stamp}.zip"
                backup_service.download_remote_file(str(remote_filename), ephemeral_path)
                zip_path = ephemeral_path
        else:
            raise ApiError(
                "请提供备份文件、backup_id 或 remote_filename",
                code=CODE_BAD_PACKAGE,
            )

        result = backup_service.restore_from_package(zip_path)
    except backup_service.BackupError as e:
        raise _api_backup_error(e) from e
    finally:
        if ephemeral_path is not None:
            try:
                ephemeral_path.unlink(missing_ok=True)
            except OSError:
                pass

    # 响应已发出后再退出，为客户端留出接收时间
    backup_service.schedule_exit(2.0)
    return success(
        result,
        msg="恢复成功，服务将在 2 秒后重启；若为手动部署且未配置进程守护，请手动重启服务",
    )
