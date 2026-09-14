"""文件分享：分享码生成、密码校验、有效期、限频与过期清理。"""
from datetime import datetime, timedelta, timezone

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..extensions import db
from ..models.file_node import FileNode
from ..models.share import Share
from ..services.cache_service import cache_delete, cache_incr, cache_ttl
from ..utils.errors import ApiError
from ..utils.security import generate_token, hash_password, verify_password

# 有效期选项（天）；0 表示永久
EXPIRE_CHOICES = (0, 1, 7, 30)

# 错误码
CODE_NOT_FOUND = 4101       # 分享不存在或已失效
CODE_EXPIRED = 4102         # 分享已过期
CODE_CANCELLED = 4103       # 分享已被取消
CODE_PWD_REQUIRED = 4104    # 需要访问密码
CODE_PWD_WRONG = 4105       # 密码错误
CODE_RATE_LIMIT = 4106      # 尝试过于频繁
CODE_FILE_GONE = 4107       # 文件已被删除
CODE_NOT_OWNER = 4108       # 无权操作该分享

# 同码同 IP 密码尝试限频：60 秒窗口内最多 5 次
_PWD_WINDOW_SECONDS = 60
_PWD_MAX_ATTEMPTS = 5
_SHARE_TOKEN_MAX_AGE = 600  # 分享访问令牌有效期 10 分钟


def create_share(user, file_id: int, password: str | None, expire_days: int) -> Share:
    """创建分享：校验归属与文件状态，生成唯一分享码。"""
    node = db.session.get(FileNode, int(file_id))
    if (
        node is None
        or node.user_id != user.id
        or node.status != "normal"
        or node.is_folder
    ):
        raise ApiError("文件不存在或不可分享", code=CODE_NOT_FOUND, http_status=404)

    days = int(expire_days or 0)
    if days not in EXPIRE_CHOICES:
        raise ApiError("有效期选项不合法", code=4109)

    expire_time = None
    if days > 0:
        expire_time = datetime.now(timezone.utc) + timedelta(days=days)

    share = Share(
        file_id=node.id,
        user_id=user.id,
        share_code=_unique_share_code(),
        share_pwd=hash_password(password) if password else None,
        expire_time=expire_time,
        status="active",
        view_count=0,
    )
    db.session.add(share)
    db.session.commit()
    return share


def _unique_share_code() -> str:
    for _ in range(10):
        code = generate_token(9)
        if not db.session.query(Share.id).filter(Share.share_code == code).first():
            return code
    raise ApiError("分享码生成失败，请重试", code=4110, http_status=500)


def get_active_share(code: str) -> Share:
    """按分享码获取有效的分享记录，并惰性处理过期状态。"""
    if not code:
        raise ApiError("分享链接无效", code=CODE_NOT_FOUND, http_status=404)
    share = db.session.query(Share).filter(Share.share_code == code).first()
    if share is None:
        raise ApiError("分享不存在或已失效", code=CODE_NOT_FOUND, http_status=404)
    if share.status == "cancelled":
        raise ApiError("分享已被取消", code=CODE_CANCELLED, http_status=403)
    if share.status == "expired" or share.is_expired():
        if share.status == "active":
            share.status = "expired"
            db.session.commit()
        raise ApiError("分享已过期", code=CODE_EXPIRED, http_status=403)
    if share.file is None or share.file.status != "normal":
        raise ApiError("分享的文件已被删除", code=CODE_FILE_GONE, http_status=410)
    return share


def _public_file_info(node: FileNode) -> dict:
    return {
        "file_name": node.file_name,
        "file_size": node.file_size,
        "file_suffix": node.file_suffix,
        "category": _category_of(node.file_suffix),
    }


def _category_of(suffix: str | None) -> str:
    table = current_app.config["CATEGORY_EXTENSIONS"]
    s = (suffix or "").lower()
    for name, exts in table.items():
        if s in exts:
            return name
    return "other"


def share_info(code: str) -> dict:
    """公开访问页所需信息：浏览数 +1；加密分享仅返回 need_password 标记。"""
    share = get_active_share(code)
    share.view_count = (share.view_count or 0) + 1
    db.session.commit()

    data = {
        "share_code": share.share_code,
        "has_password": bool(share.share_pwd),
        "need_password": bool(share.share_pwd),
        "view_count": share.view_count,
        "expire_time": share.expire_time.isoformat() if share.expire_time else None,
        "file": _public_file_info(share.file),
        "token": None,
    }
    # 公开分享直接签发访问令牌；加密分享待密码校验后签发
    if not share.share_pwd:
        data["token"] = issue_access_token(share.share_code)
        data["need_password"] = False
    return data


def verify_share_password(code: str, password: str, ip: str) -> dict:
    """校验分享密码，通过后返回访问令牌；同码同 IP 限频防爆破。"""
    share = get_active_share(code)
    if not share.share_pwd:
        return {"token": issue_access_token(code), "need_password": False}

    # 限频：同码同 IP 在窗口期内最多 N 次（Redis/内存原子递增）
    rate_key = f"share:pwd:{code}:{ip or 'unknown'}"
    attempts = cache_incr(rate_key, ttl=_PWD_WINDOW_SECONDS)
    if attempts > _PWD_MAX_ATTEMPTS:
        retry_after = max(cache_ttl(rate_key), 1)
        raise ApiError(
            f"尝试过于频繁，请 {retry_after} 秒后再试",
            code=CODE_RATE_LIMIT,
            http_status=429,
        )

    if not password or not verify_password(password, share.share_pwd):
        raise ApiError("访问密码错误", code=CODE_PWD_WRONG, http_status=403)

    # 校验通过：清除限频计数
    cache_delete(rate_key)
    return {"token": issue_access_token(code), "need_password": False}


def issue_access_token(code: str) -> str:
    """签发 10 分钟有效的分享访问令牌（仅用于匿名信息/下载）。"""
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="share-access")
    return serializer.dumps({"code": code})


def verify_access_token(code: str, token: str | None) -> None:
    """校验分享下载令牌与分享码匹配且未过期。"""
    if not token:
        raise ApiError("请先完成访问验证", code=CODE_PWD_REQUIRED, http_status=403)
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="share-access")
    try:
        payload = serializer.loads(token, max_age=_SHARE_TOKEN_MAX_AGE)
    except SignatureExpired:
        raise ApiError("访问凭证已过期，请重新验证", code=CODE_PWD_REQUIRED, http_status=403)
    except BadSignature:
        raise ApiError("访问凭证无效", code=CODE_PWD_REQUIRED, http_status=403)
    if payload.get("code") != code:
        raise ApiError("访问凭证与分享不匹配", code=CODE_PWD_REQUIRED, http_status=403)


def resolve_share_download(code: str, token: str | None) -> Share:
    """匿名下载前的完整校验，返回分享记录。"""
    share = get_active_share(code)
    verify_access_token(code, token)
    if share.file.is_folder:
        raise ApiError("文件夹暂不支持下载", code=4111)
    return share


def list_shares(user, page: int, size: int, keyword: str | None = None) -> dict:
    query = db.session.query(Share).filter(Share.user_id == user.id)
    if keyword:
        escaped = (
            keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        query = query.join(FileNode, FileNode.id == Share.file_id).filter(
            FileNode.file_name.like(f"%{escaped}%", escape="\\")
        )
    total = query.count()
    rows = (
        query.order_by(Share.create_time.desc())
        .offset(max(page - 1, 0) * size)
        .limit(size)
        .all()
    )
    items = []
    for s in rows:
        item = s.to_dict()
        # 列表附带实时有效性，供前端展示"剩余有效期"
        item["effective"] = s.status == "active" and not s.is_expired()
        items.append(item)
    return {"total": total, "page": page, "size": size, "items": items}


def cancel_share(user, share_id: int) -> None:
    share = db.session.get(Share, int(share_id))
    if share is None or share.user_id != user.id:
        raise ApiError("分享不存在或无权操作", code=CODE_NOT_OWNER, http_status=404)
    share.status = "cancelled"
    db.session.commit()


def cleanup_expired() -> int:
    """定时任务/多进程兜底：把到期记录批量置为 expired。"""
    now = datetime.now(timezone.utc)
    count = (
        db.session.query(Share)
        .filter(Share.status == "active", Share.expire_time.isnot(None), Share.expire_time <= now)
        .update({Share.status: "expired"}, synchronize_session=False)
    )
    db.session.commit()
    return count
