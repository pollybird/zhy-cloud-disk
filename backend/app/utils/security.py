"""密码哈希与随机串生成。"""
import secrets

import bcrypt


def hash_password(raw: str) -> str:
    """bcrypt 加盐哈希。"""
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    if not raw or not hashed:
        return False
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def generate_token(nbytes: int = 24) -> str:
    """高熵随机码（分享码、JWT 密钥等）。"""
    return secrets.token_urlsafe(nbytes)
