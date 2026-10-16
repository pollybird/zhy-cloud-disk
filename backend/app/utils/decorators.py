"""鉴权装饰器：登录校验、角色校验、资源归属校验。"""
import functools

from flask import g
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from ..extensions import db
from .errors import ApiError


def login_required(fn):
    """要求有效 JWT，并将当前用户挂载到 g.current_user。"""

    @functools.wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        from ..models.user import User

        user_id = get_jwt_identity()
        user = db.session.get(User, int(user_id)) if user_id is not None else None
        if user is None:
            raise ApiError("用户不存在或登录已失效", code=4014, http_status=401)
        if user.status != "active":
            raise ApiError("账号已被禁用，请联系管理员", code=4031, http_status=403)
        # M3：令牌版本不匹配（改密/重置密码/禁用后签发的旧令牌）→ 拒绝。
        # 无 tv 声明的历史令牌放行，待其自然过期。
        tv = get_jwt().get("tv")
        if tv is not None and tv != (user.token_version or 1):
            raise ApiError("登录状态已失效，请重新登录", code=4015, http_status=401)
        g.current_user = user
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    """要求当前用户为管理员。"""

    @functools.wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if g.current_user.role != "admin":
            raise ApiError("需要管理员权限", code=4030, http_status=403)
        return fn(*args, **kwargs)

    return wrapper


def current_user():
    """获取 g.current_user（须在 login_required 之后使用）。"""
    return getattr(g, "current_user", None)
