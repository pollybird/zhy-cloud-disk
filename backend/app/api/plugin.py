"""插件接口：管理（管理员）+ 通用插件 API（文件流/保存/权限校验/可用插件查询）。

设计稿 6.4 通用插件 API：
- GET  /api/plugin/file/stream  文件流读取（归属 JWT 或分享 code+token 鉴权）
- POST /api/plugin/file/save    编辑保存回调（重新走配额与类型校验，仅归属用户）
- GET  /api/plugin/auth/check   权限校验（归属/分享双身份）
- POST /api/plugin/register     插件注册（重扫描注册表，可顺带启用指定插件）
"""
import os
import tempfile

from flask import Blueprint, current_app, g, request, send_file
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from ..extensions import db
from ..models.download_log import DownloadLog
from ..models.file_node import FileNode
from ..models.user import User
from ..plugins.manager import manager
from ..services import file_service, share_service
from ..utils.decorators import admin_required, current_user, login_required
from ..utils.errors import ApiError
from ..utils.response import success

bp = Blueprint("plugin", __name__, url_prefix="/api/plugin")

# 错误码
CODE_FOLDER = 5202         # 文件夹不支持流读取/保存
CODE_SAVE_INVALID = 5203   # 保存内容不合法
CODE_PLUGIN_SUFFIX = 5204  # 插件不支持该后缀
CODE_PLUGIN_DENIED = 5205  # 插件权限钩子拒绝


# ---------------------------------------------------------------------------
# 内部工具：统一解析"归属 / 分享态"两种访问身份
# ---------------------------------------------------------------------------

def _load_jwt_user() -> User | None:
    """尝试加载 JWT 归属用户；无凭证/失效/被禁用返回 None。"""
    try:
        verify_jwt_in_request()
    except Exception:
        return None
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id)) if user_id is not None else None
    if user is None or user.status != "active":
        return None
    g.current_user = user
    return user


def _resolve_access() -> tuple[FileNode, str, object | None]:
    """解析访问身份，返回 (node, access, share)。

    - id= 存在 → JWT 归属访问（无有效凭证返回 401）
    - 否则 code+token= → 分享访客（复用分享下载校验链）
    """
    file_id = request.args.get("id", type=int)
    if file_id:
        user = _load_jwt_user()
        if user is None:
            raise ApiError("请先登录", code=4010, http_status=401)
        node = file_service.get_owned_node(user, file_id)
        return node, "owner", None

    code = (request.args.get("code") or "").strip()
    if code:
        share = share_service.resolve_share_download(code, request.args.get("token"))
        return share.file, "share", share

    raise ApiError("缺少文件参数（id 或 code+token）", code=5201, http_status=400)


def _plugin_hook(node: FileNode, action: str) -> None:
    """存在 plugin 参数时：校验插件已启用且支持该后缀，并执行权限钩子。"""
    name = (request.args.get("plugin") or "").strip()
    if not name:
        return
    instance = manager.get(name)
    if instance is None:
        raise ApiError("插件未启用或不存在", code=5102, http_status=403)
    if node.file_suffix.lower() not in instance.supported_exts:
        raise ApiError("该插件不支持此文件类型", code=CODE_PLUGIN_SUFFIX)
    if not instance.check_permission(current_user(), node, action):
        raise ApiError("插件拒绝了本次操作", code=CODE_PLUGIN_DENIED, http_status=403)


def _log_download(node: FileNode, share_id: int | None) -> None:
    """写下载日志；带 Range 的流式拖动（视频 seek）不记，避免刷日志。"""
    if "Range" in request.headers:
        return
    user = current_user()
    db.session.add(
        DownloadLog(
            user_id=user.id if user else None,
            file_id=node.id,
            share_id=share_id,
            ip=request.remote_addr,
            user_agent=(request.user_agent.string or "")[:500],
        )
    )
    db.session.commit()


# ---------------------------------------------------------------------------
# 通用插件 API
# ---------------------------------------------------------------------------

@bp.get("/file/stream")
def file_stream():
    """文件流读取（内联）：归属用户或有效分享访客；支持 Range 断点。"""
    node, _access, share = _resolve_access()
    if node.is_folder:
        raise ApiError("文件夹不支持流读取", code=CODE_FOLDER)

    _plugin_hook(node, "stream")
    path = file_service.storage_service.open_physical(node.save_path)
    if not path.is_file():
        raise ApiError("物理文件已丢失", code=3204, http_status=410)

    _log_download(node, share.id if share else None)
    return send_file(path, as_attachment=False, conditional=True)


@bp.post("/file/save")
@login_required
def file_save():
    """编辑保存回调（H2 整改）。

    - 必须具备写权限（部门文件经 permission + 排他锁双重校验）；
    - 容量增量按"所在范围"扣减（部门文件扣部门配额，部门 0=不限）；
    - 共享内容块（ref_count>1）绝不原地覆盖：新内容注册为独立 blob，
      旧引用释放（归零时物理删除），避免污染其他引用者；
    - 1.0/1.1 旧版非 blob（legacy）文件提交成功后再删除原物理文件。
    """
    import hashlib

    from sqlalchemy import and_, update

    from ..models.department import Department
    from ..models.file_blob import FileBlob
    from ..services import blob_service, file_lock_service

    payload = request.get_json(silent=True) or {}
    file_id = int(payload.get("id") or 0)
    if not file_id:
        raise ApiError("缺少文件 id", code=5201, http_status=400)

    user = current_user()
    # H2-1：required="write"（内部已做写权限与排他锁校验），再显式确认一次锁
    node = file_service.get_owned_node(user, file_id, required="write")
    if node.is_folder:
        raise ApiError("文件夹不支持保存", code=CODE_SAVE_INVALID)
    file_lock_service.ensure_unlocked(user, node)

    _plugin_hook(node, "save")

    # 读取新内容：JSON 文本（编辑器场景）或 multipart 文件（二进制场景）
    if payload.get("content") is not None:
        if not isinstance(payload.get("content"), str):
            raise ApiError("content 必须为字符串", code=CODE_SAVE_INVALID)
        content = payload["content"].encode("utf-8")
    else:
        fs = request.files.get("file")
        if fs is None:
            raise ApiError("缺少保存内容（content 或 file 字段）", code=CODE_SAVE_INVALID)
        content = fs.stream.read()

    if not content:
        raise ApiError("保存内容不能为空", code=CODE_SAVE_INVALID)

    # 类型校验：以现文件名为准，禁止保存成黑名单后缀
    suffix = file_service.storage_service.extract_suffix(node.file_name)
    if suffix in current_app.config["DENIED_EXTENSIONS"]:
        raise ApiError(f"禁止保存 .{suffix} 类型的文件", code=3105)

    new_size = len(content)
    new_hash = hashlib.md5(content).hexdigest()
    old_size = int(node.file_size or 0)
    delta = new_size - old_size

    # 内容未变化：无需任何配额/物理操作
    if new_hash == node.file_hash and new_size == old_size:
        return success(node.to_dict(), msg="内容无变化")

    # 新内容先落暂存（与 blob 同卷，后续 os.replace 为原子同盘移动）
    staged_path = None
    fd, tmp_name = tempfile.mkstemp(
        dir=str(file_service.storage_service.staging_dir()), suffix=".save"
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        staged_path = tmp_name
    except OSError:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise ApiError("保存失败：无法写入暂存文件", code=CODE_SAVE_INVALID)

    # 物理文件丢失检查前置：此时尚未扣减配额，直接拒绝
    old_save_path = node.save_path
    if not old_save_path or not file_service.storage_service.open_physical(
        old_save_path
    ).is_file():
        file_service.storage_service.remove_staging(staged_path)
        raise ApiError("物理文件已丢失", code=3204, http_status=410)

    # 旧引用形态：blob（去重文件）/ legacy（1.0/1.1 旧文件）/ missing（漂移）
    old_blob = None
    legacy_old_path = None
    if file_service.storage_service.is_blob_path(old_save_path) and node.file_hash:
        old_blob = (
            db.session.query(FileBlob)
            .filter(FileBlob.file_hash == node.file_hash)
            .first()
        )
    elif not file_service.storage_service.is_blob_path(old_save_path):
        legacy_old_path = old_save_path

    removed_blob_path: str | None = None
    try:
        # H2-2：配额增量按所在范围扣减（与上传同一口径）
        if delta > 0:
            if not file_service._charge_quota(user.id, node.department_id, delta):
                raise ApiError("存储空间不足，保存被拒绝", code=3106, http_status=413)
        elif delta < 0:
            _decrease_quota(user.id, node.department_id, -delta)

        # H2-3：新内容注册为独立 blob（可能与他人内容相同而被去重复用）
        new_blob = blob_service.get_or_create(new_hash, new_size, staged_path)
        staged_path = None  # get_or_create 已移入 blob 目录或已丢弃暂存
        blob_service.retain(new_blob)

        # 释放本节点对旧内容的一次引用
        if old_blob is not None:
            removed_blob_path = blob_service.release(old_blob)

        node.save_path = new_blob.save_path
        node.file_hash = new_hash
        node.file_size = new_size
        db.session.commit()
    except ApiError:
        db.session.rollback()
        if staged_path:
            file_service.storage_service.remove_staging(staged_path)
        raise
    except Exception:
        db.session.rollback()
        if staged_path:
            file_service.storage_service.remove_staging(staged_path)
        raise ApiError("保存失败，请重试", code=CODE_SAVE_INVALID)

    # 提交成功后再清理旧物理文件（失败不影响数据一致性）
    if removed_blob_path and os.path.exists(removed_blob_path):
        try:
            os.unlink(removed_blob_path)
        except OSError:
            pass
    if legacy_old_path:
        try:
            p = file_service.storage_service.open_physical(legacy_old_path)
            if p.is_file():
                p.unlink()
        except (OSError, ApiError):
            pass

    db.session.refresh(user)
    return success(node.to_dict(), msg="保存成功")


def _decrease_quota(user_id: int, department_id: int | None, size: int) -> None:
    """原子回退逻辑配额（不低于 0）；部门无限额同样统计用量。"""
    from sqlalchemy import and_, update

    from ..models.department import Department

    if size <= 0:
        return
    if department_id:
        model, col, filt = (
            Department,
            Department.used_storage,
            Department.id == department_id,
        )
    else:
        model, col, filt = User, User.used_storage, User.id == user_id
    result = db.session.execute(
        update(model)
        .where(and_(filt, col - size >= 0))
        .values(used_storage=col - size)
    )
    if result.rowcount == 0:
        # 用量数据异常（理论不应出现）：钳制到 0
        db.session.execute(update(model).where(filt).values(used_storage=0))


def _refund_quota_scope(user_id: int, department_id: int | None, delta: int) -> None:
    """H2-4：按所在范围回退配额（行锁读改写，供失败补偿场景使用）。"""
    if delta <= 0:
        return
    from ..models.department import Department

    if department_id:
        locked = (
            db.session.query(Department)
            .filter(Department.id == department_id)
            .with_for_update()
            .first()
        )
    else:
        locked = (
            db.session.query(User)
            .filter(User.id == user_id)
            .with_for_update()
            .first()
        )
    if locked is not None:
        locked.used_storage = max(int(locked.used_storage) - delta, 0)
        db.session.commit()


@bp.get("/auth/check")
def auth_check():
    """权限校验：返回访问身份、文件信息与该后缀可用的已启用插件。"""
    node, access, _share = _resolve_access()
    user = current_user()
    data = {
        "allowed": True,
        "access": access,
        "file": {
            "id": node.id,
            "file_name": node.file_name,
            "file_suffix": node.file_suffix,
            "file_size": node.file_size,
            "is_folder": node.is_folder,
        },
        "user": user.username if user else None,
        "plugins": manager.available_for_suffix(node.file_suffix),
    }
    return success(data)


@bp.get("/available")
@login_required
def available():
    """按后缀查询已启用插件（前端预览挂载点使用）。"""
    suffix = (request.args.get("suffix") or "").strip()
    return success({"items": manager.available_for_suffix(suffix)})


@bp.post("/register")
@admin_required
def register_plugin():
    """插件注册：重扫描插件目录并同步注册表；可选顺带启用指定插件。"""
    payload = request.get_json(silent=True) or {}
    app = current_app._get_current_object()
    manager.rescan(app)
    name = (payload.get("name") or "").strip()
    scan = {"items": manager.list_records(), "scan_errors": manager.scan_errors()}
    if name:
        row = manager.enable(app, name)
        return success(
            {**scan, "enabled": row},
            msg=f"插件 {name} 已注册并启用",
        )
    return success(scan, msg="插件注册表已更新")


# ---------------------------------------------------------------------------
# 管理接口（仅管理员）
# ---------------------------------------------------------------------------

@bp.get("/list")
@admin_required
def plugin_list():
    return success(
        {
            "items": manager.list_records(),
            "loaded": manager.loaded_names(),
            "scan_errors": manager.scan_errors(),
        }
    )


@bp.put("/<name>/enabled")
@admin_required
def set_enabled(name: str):
    payload = request.get_json(silent=True) or {}
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise ApiError("enabled 必须为布尔值", code=5104)
    app = current_app._get_current_object()
    row = manager.enable(app, name) if enabled else manager.disable(app, name)
    return success({"plugin": row}, msg="已启用" if enabled else "已禁用")
