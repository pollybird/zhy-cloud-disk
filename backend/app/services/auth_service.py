"""认证业务：注册、登录、令牌签发。"""
from flask import current_app
from flask_jwt_extended import create_access_token, create_refresh_token
from sqlalchemy import or_

from ..extensions import db
from ..models.user import User
from ..services import setting_service
from ..utils.errors import ApiError
from ..utils.security import hash_password, verify_password
from ..utils.validators import validate_email, validate_password, validate_username


def register(username: str, email: str, password: str) -> User:
    if not setting_service.is_register_allowed():
        raise ApiError("系统当前未开放注册，如需账号请联系管理员", code=1100, http_status=403)

    username = validate_username(username)
    email = validate_email(email)
    password = validate_password(password)

    exists = (
        db.session.query(User)
        .filter(or_(User.username == username, User.email == email))
        .first()
    )
    if exists:
        raise ApiError("用户名或邮箱已被注册", code=1101, http_status=409)

    user = User(
        username=username,
        email=email,
        password=hash_password(password),
        role="user",
        status="active",
        total_storage=int(current_app.config["DEFAULT_QUOTA"]),
        used_storage=0,
    )
    db.session.add(user)
    db.session.commit()
    return user


def authenticate(login_name: str, password: str) -> tuple[User, str, str]:
    """用户名或邮箱 + 密码登录，返回 (user, access_token, refresh_token)。"""
    login_name = (login_name or "").strip()
    if not login_name or not password:
        raise ApiError("请输入用户名和密码", code=1102)

    user = (
        db.session.query(User)
        .filter(or_(User.username == login_name, User.email == login_name.lower()))
        .first()
    )
    if user is None or not verify_password(password, user.password):
        raise ApiError("用户名或密码错误", code=1103, http_status=401)
    if user.status != "active":
        raise ApiError("账号已被禁用，请联系管理员", code=4031, http_status=403)

    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))
    return user, access_token, refresh_token


def issue_tokens(user: User) -> dict:
    return {
        "access_token": create_access_token(identity=str(user.id)),
        "refresh_token": create_refresh_token(identity=str(user.id)),
        "user": user.to_dict(),
    }
