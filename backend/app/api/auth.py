"""认证接口：注册、登录、令牌刷新、退出。"""
from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from ..services import auth_service
from ..utils.decorators import current_user, login_required
from ..utils.response import success

bp = Blueprint("auth", __name__, url_prefix="/api")


@bp.get("/auth/register-status")
def register_status():
    """公开接口：当前是否开放游客注册（供登录/注册页展示）。"""
    from ..services import setting_service

    return success({"allow_register": setting_service.is_register_allowed()})


@bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    user = auth_service.register(
        data.get("username", ""),
        data.get("email", ""),
        data.get("password", ""),
    )
    return success({"user": user.to_dict()}, msg="注册成功")


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    user, access_token, refresh_token = auth_service.authenticate(
        data.get("username", ""), data.get("password", "")
    )
    return success(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": user.to_dict(),
        },
        msg="登录成功",
    )


@bp.post("/auth/refresh")
@jwt_required(refresh=True)
def refresh():
    from ..extensions import db
    from ..models.user import User

    user = db.session.get(User, int(get_jwt_identity()))
    if user is None or user.status != "active":
        from ..utils.errors import ApiError

        raise ApiError("账号不可用，请重新登录", code=4014, http_status=401)
    return success(auth_service.issue_tokens(user), msg="令牌已刷新")


@bp.post("/logout")
@login_required
def logout():
    """吊销当前 access token 的 jti，使其后续请求立即失效。"""
    from flask_jwt_extended import get_jwt

    from ..services.cache_service import cache_set

    jti = get_jwt().get("jti")
    if jti:
        # TTL 与 access token 剩余有效期对齐，过期后自动清理
        from datetime import datetime, timezone

        exp = get_jwt().get("exp")
        if exp:
            ttl = max(int(exp - datetime.now(timezone.utc).timestamp()), 1)
        else:
            ttl = 7200  # 回退：access token 默认有效期
        cache_set(f"jwt:revoked:{jti}", 1, ttl=ttl)
    return success(msg="已退出登录")
