"""文件分享接口：创建、公开访问、密码校验、下载、我的分享管理。"""
from flask import Blueprint, request, send_file

from ..models.download_log import DownloadLog
from ..extensions import db
from ..services import file_service, share_service
from ..utils.decorators import current_user, login_required
from ..utils.errors import ApiError
from ..utils.response import success

bp = Blueprint("share", __name__, url_prefix="/api/share")


@bp.post("/create")
@login_required
def create():
    data = request.get_json(silent=True) or {}
    file_id = int(data.get("file_id") or 0)
    password = (data.get("password") or "").strip() or None
    if password is not None and not (1 <= len(password) <= 32):
        raise ApiError("分享密码长度需为 1-32 位", code=4112)
    expire_days = int(data.get("expire_days") or 0)
    share = share_service.create_share(current_user(), file_id, password, expire_days)
    return success(share.to_dict(), msg="分享创建成功")


@bp.get("/info")
def info():
    """公开接口：返回分享脱敏信息（浏览数 +1）。"""
    code = (request.args.get("code") or "").strip()
    return success(share_service.share_info(code))


@bp.post("/verify-password")
def verify_password():
    """公开接口：校验加密分享密码，通过后签发访问令牌。"""
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    password = data.get("password") or ""
    result = share_service.verify_share_password(code, password, request.remote_addr)
    return success(result, msg="验证成功")


@bp.get("/list")
@login_required
def share_list():
    page = max(int(request.args.get("page", 1)), 1)
    size = min(max(int(request.args.get("size", 50)), 1), 200)
    keyword = request.args.get("keyword") or None
    return success(share_service.list_shares(current_user(), page, size, keyword))


@bp.delete("/cancel")
@login_required
def cancel():
    share_id = int(request.args.get("id") or (request.get_json(silent=True) or {}).get("id") or 0)
    share_service.cancel_share(current_user(), share_id)
    return success(msg="分享已取消")


@bp.get("/download")
def download():
    """匿名分享下载：需携带 info/verify-password 签发的访问令牌。"""
    code = (request.args.get("code") or "").strip()
    token = request.args.get("token")
    share = share_service.resolve_share_download(code, token)
    node = share.file

    path = file_service.storage_service.open_physical(node.save_path)
    if not path.is_file():
        raise ApiError("物理文件已丢失", code=share_service.CODE_FILE_GONE, http_status=410)

    db.session.add(
        DownloadLog(
            user_id=None,
            file_id=node.id,
            share_id=share.id,
            ip=request.remote_addr,
            user_agent=(request.user_agent.string or "")[:500],
        )
    )
    db.session.commit()

    return send_file(
        path,
        as_attachment=True,
        download_name=node.file_name,
        conditional=True,
    )
