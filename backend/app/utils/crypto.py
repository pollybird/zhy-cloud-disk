"""对称加密工具：用于加密存库的敏感配置（如远端备份密码）。

密钥由 Flask SECRET_KEY 经 SHA256 派生（Fernet 需要 32 字节 urlsafe base64）。
注意：更换 SECRET_KEY 后旧密文无法解密，需在后台重新配置密码。
"""
from __future__ import annotations

import base64
import hashlib

import cryptography.fernet


class SecretDecryptError(Exception):
    """密文损坏或密钥不匹配。"""


def _fernet(secret_key: str) -> cryptography.fernet.Fernet:
    digest = hashlib.sha256((secret_key or "").encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return cryptography.fernet.Fernet(key)


def encrypt_secret(plaintext: str, secret_key: str) -> str:
    """加密；空字符串原样返回（表示未配置）。"""
    if plaintext is None or plaintext == "":
        return ""
    token = _fernet(secret_key).encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_secret(token: str, secret_key: str) -> str:
    """解密；空字符串原样返回；失败抛 SecretDecryptError。"""
    if not token:
        return ""
    try:
        return _fernet(secret_key).decrypt(token.encode("ascii")).decode("utf-8")
    except cryptography.fernet.InvalidToken as exc:
        raise SecretDecryptError("密文无法解密（SECRET_KEY 可能已变更）") from exc
