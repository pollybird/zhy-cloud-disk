"""输入校验工具。"""
import re

from .errors import ApiError

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-一-龥]{3,32}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DB_TYPES = {"sqlite", "mysql", "postgresql"}


def validate_username(username: str) -> str:
    username = (username or "").strip()
    if not USERNAME_PATTERN.match(username):
        raise ApiError("用户名需为 3-32 位中英文、数字、下划线或连字符", code=1001)
    return username


def validate_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not email or len(email) > 128 or not EMAIL_PATTERN.match(email):
        raise ApiError("邮箱格式不正确", code=1002)
    return email


def validate_password(password: str) -> str:
    """密码强度：8-64 位，须同时包含字母和数字。"""
    if not password or not 8 <= len(password) <= 64:
        raise ApiError("密码长度需为 8-64 位", code=1003)
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ApiError("密码须同时包含字母和数字", code=1004)
    return password
