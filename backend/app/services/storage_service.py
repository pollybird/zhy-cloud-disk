"""物理文件存储服务：UUID 物理文件名、分用户目录、流式落盘、安全路径。"""
import hashlib
import os
import uuid
from pathlib import Path

from flask import current_app

from ..utils.errors import ApiError

CHUNK_SIZE = 1024 * 1024  # 1MB 分块


def storage_root() -> Path:
    root = Path(current_app.config["STORAGE_DIR"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def user_dir(user_id: int) -> Path:
    path = (storage_root() / str(int(user_id))).resolve()
    # 防穿越：必须位于存储根内
    if not _is_within(storage_root(), path):
        raise ApiError("非法的存储路径", code=3001)
    path.mkdir(parents=True, exist_ok=True)
    return path


def extract_suffix(filename: str) -> str:
    """提取小写后缀（不带点），无后缀返回空串。"""
    if not filename or "." not in filename:
        return ""
    suffix = filename.rsplit(".", 1)[1].strip().lower()
    return suffix[:32]


def physical_name(suffix: str) -> str:
    name = uuid.uuid4().hex
    return f"{name}.{suffix}" if suffix else name


def safe_original_name(filename: str) -> str:
    """校验用户文件名：仅取基名防穿越，清理控制符与非法字符，保留中文。"""
    filename = (filename or "").replace("\\", "/").split("/")[-1]
    # 清理控制字符与文件系统非法字符（U+0000-U+001F、/ \\ : * ? " < > |）
    cleaned = "".join(
        ch
        for ch in filename
        if ord(ch) >= 32 and ch not in '/\\:*?"<>|'
    ).strip(" .")
    if not cleaned or cleaned in {".", ".."}:
        raise ApiError("文件名不合法", code=3002)
    return cleaned[:255]


def save_stream(file_storage, user_id: int) -> tuple[str, str, int]:
    """将上传流分块写入磁盘。

    返回 (save_path, suffix, size)；文件名使用 UUID 防覆盖。
    """
    original = safe_original_name(file_storage.filename)
    suffix = extract_suffix(original)
    target_dir = user_dir(user_id)
    target = target_dir / physical_name(suffix)
    size = 0
    try:
        with open(target, "wb") as f:
            while True:
                chunk = file_storage.stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                f.write(chunk)
    except OSError as e:
        remove_physical(str(target))
        raise ApiError(f"文件保存失败：{e}", code=3003)
    return str(target), suffix, size


def save_stream_hashed(file_storage, user_id: int) -> tuple[str, str, int, str]:
    """流式落盘并增量计算 MD5，返回 (save_path, suffix, size, md5_hex)。"""
    original = safe_original_name(file_storage.filename)
    suffix = extract_suffix(original)
    target_dir = user_dir(user_id)
    target = target_dir / physical_name(suffix)
    size = 0
    h = hashlib.md5()
    try:
        with open(target, "wb") as f:
            while True:
                chunk = file_storage.stream.read(CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                f.write(chunk)
                h.update(chunk)
    except OSError as e:
        remove_physical(str(target))
        raise ApiError(f"文件保存失败：{e}", code=3003)
    return str(target), suffix, size, h.hexdigest()


def open_physical(save_path: str) -> Path:
    """校验物理路径安全并返回 Path（不检查存在性）。"""
    if not save_path:
        raise ApiError("文件路径缺失", code=3004)
    path = Path(save_path).resolve()
    if not _is_within(storage_root(), path):
        raise ApiError("非法的文件访问路径", code=3005)
    return path


def remove_physical(save_path: str) -> bool:
    try:
        path = Path(save_path).resolve()
        if _is_within(storage_root(), path) and path.is_file():
            path.unlink()
            return True
    except OSError:
        return False
    return False


def _is_within(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
