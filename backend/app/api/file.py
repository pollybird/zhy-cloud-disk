"""文件管理接口：上传、下载、列表、目录操作。"""
from flask import Blueprint, request, send_file

from ..models.download_log import DownloadLog
from ..extensions import db
from ..services import file_service
from ..utils.decorators import current_user, login_required
from ..utils.errors import ApiError
from ..utils.response import success

bp = Blueprint("file", __name__, url_prefix="/api")


@bp.post("/file/upload")
@login_required
def upload():
    files = request.files.getlist("files")
    if not files:
        raise ApiError("未选择上传文件", code=3201)
    raw_parent = request.form.get("parent_id")
    parent_id = int(raw_parent) if raw_parent else None
    file_hash = request.form.get("file_hash") or None
    mode = request.form.get("mode") or "normal"
    overwrite_id_raw = request.form.get("overwrite_id")
    overwrite_id = int(overwrite_id_raw) if overwrite_id_raw else None
    raw_dept = request.form.get("department_id")
    department_id = int(raw_dept) if raw_dept else None

    results = {"success": [], "failed": []}
    for fs in files:
        try:
            node = file_service.upload_file(
                current_user(), fs, parent_id,
                file_hash=file_hash, mode=mode, overwrite_id=overwrite_id,
                department_id=department_id,
            )
            results["success"].append(node.to_dict())
        except ApiError as e:
            results["failed"].append({"file_name": fs.filename, "msg": e.msg})

    return success(results, msg=f"上传完成：成功 {len(results['success'])} 个")


@bp.post("/file/check-duplicate")
@login_required
def check_duplicate():
    """上传前预检同名文件冲突。"""
    data = request.get_json(silent=True) or {}
    parent_id = data.get("parent_id")
    file_name = data.get("file_name", "")
    file_hash = data.get("file_hash") or None
    department_id = data.get("department_id")
    if not file_name:
        raise ApiError("缺少文件名", code=3202)
    result = file_service.check_duplicate(
        current_user(),
        int(parent_id) if parent_id else None,
        file_name,
        file_hash,
        int(department_id) if department_id else None,
    )
    return success(result)


@bp.post("/file/instant")
@login_required
def instant_upload():
    """跨用户秒传：凭整文件 MD5+大小直接建引用，零上传流量。"""
    data = request.get_json(silent=True) or {}
    parent_id = data.get("parent_id")
    department_id = data.get("department_id")
    result = file_service.instant_upload(
        current_user(),
        int(parent_id) if parent_id else None,
        int(department_id) if department_id else None,
        data.get("file_name", ""),
        int(data.get("file_size") or 0),
        data.get("file_hash") or None,
    )
    return success(result, msg="秒传完成" if result.get("instant") else "未命中秒传")


@bp.post("/file/chunk/init")
@login_required
def chunk_init():
    """初始化/恢复分片上传会话。"""
    data = request.get_json(silent=True) or {}
    raw_chunk = data.get("chunk_size")
    result = file_service.chunk_init(
        current_user(),
        int(data["parent_id"]) if data.get("parent_id") else None,
        int(data["department_id"]) if data.get("department_id") else None,
        data.get("file_name", ""),
        int(data.get("file_size") or 0),
        data.get("file_hash") or None,
        int(raw_chunk) if raw_chunk else None,
    )
    return success(result)


@bp.post("/file/chunk/upload")
@login_required
def chunk_upload():
    """上传单个分片（幂等：重复序号覆盖）。"""
    part = request.files.get("chunk")
    if part is None:
        raise ApiError("缺少分片数据", code=3201)
    upload_id = request.form.get("upload_id")
    if not upload_id:
        raise ApiError("缺少 upload_id", code=3207)
    index_raw = request.form.get("index")
    if index_raw is None:
        raise ApiError("缺少分片序号", code=3208)
    result = file_service.chunk_upload(
        current_user(),
        upload_id,
        int(index_raw),
        request.form.get("chunk_hash") or None,
        part,
    )
    return success(result)


@bp.post("/file/chunk/complete")
@login_required
def chunk_complete():
    """合并全部分片并完成上传。"""
    data = request.get_json(silent=True) or {}
    upload_id = data.get("upload_id")
    if not upload_id:
        raise ApiError("缺少 upload_id", code=3207)
    return success(file_service.chunk_complete(current_user(), upload_id))


@bp.post("/file/chunk/abort")
@login_required
def chunk_abort():
    """取消分片上传并清理暂存。"""
    data = request.get_json(silent=True) or {}
    upload_id = data.get("upload_id")
    if not upload_id:
        raise ApiError("缺少 upload_id", code=3207)
    return success(file_service.chunk_abort(current_user(), upload_id))


@bp.get("/file/chunk/status")
@login_required
def chunk_status():
    """查询分片会话已收分片（断点恢复）。"""
    upload_id = request.args.get("upload_id")
    if not upload_id:
        raise ApiError("缺少 upload_id", code=3207)
    return success(file_service.chunk_status(current_user(), upload_id))


# ---- 1.2.0 部门文件排他编辑锁 ----

@bp.post("/file/lock/acquire")
@login_required
def lock_acquire():
    """打开部门文件编辑前获取排他锁（幂等，重复获取即续约）。"""
    from ..services import file_lock_service

    data = request.get_json(silent=True) or {}
    node_id = data.get("id")
    if not node_id:
        raise ApiError("缺少文件 id", code=3202)
    return success(file_lock_service.acquire(current_user(), int(node_id)))


@bp.post("/file/lock/heartbeat")
@login_required
def lock_heartbeat():
    """编辑期间定期续约，防止锁过期。"""
    from ..services import file_lock_service

    data = request.get_json(silent=True) or {}
    node_id = data.get("id")
    if not node_id:
        raise ApiError("缺少文件 id", code=3202)
    return success(file_lock_service.renew(current_user(), int(node_id)))


@bp.post("/file/lock/release")
@login_required
def lock_release():
    """保存完成/关闭文件后释放锁；管理员可 force 释放他人锁。"""
    from ..services import file_lock_service

    data = request.get_json(silent=True) or {}
    node_id = data.get("id")
    if not node_id:
        raise ApiError("缺少文件 id", code=3202)
    return success(
        file_lock_service.release(current_user(), int(node_id), force=bool(data.get("force")))
    )


@bp.get("/file/lock/status")
@login_required
def lock_status():
    """查询单个文件当前锁状态。"""
    from ..services import file_lock_service

    node_id = request.args.get("id")
    if not node_id:
        raise ApiError("缺少文件 id", code=3202)
    return success(file_lock_service.status(current_user(), int(node_id)))


@bp.get("/file/list")
@login_required
def file_list():
    parent_raw = request.args.get("parent_id")
    parent_id = int(parent_raw) if parent_raw else None
    dept_raw = request.args.get("department_id")
    department_id = int(dept_raw) if dept_raw else None
    category = request.args.get("category") or None
    keyword = request.args.get("keyword") or None
    page = max(int(request.args.get("page", 1)), 1)
    size = min(max(int(request.args.get("size", 50)), 1), 200)
    return success(
        file_service.list_files(
            current_user(), parent_id, department_id, category, keyword, page, size
        )
    )


@bp.get("/file/folders")
@login_required
def child_folders():
    parent_raw = request.args.get("parent_id")
    parent_id = int(parent_raw) if parent_raw else None
    dept_raw = request.args.get("department_id")
    department_id = int(dept_raw) if dept_raw else None
    return success({
        "items": file_service.list_child_folders(
            current_user(), parent_id, department_id
        )
    })


@bp.get("/file/download")
@login_required
def download():
    file_id = request.args.get("id", type=int)
    if not file_id:
        raise ApiError("缺少文件 id", code=3202)
    node = file_service.get_owned_node(current_user(), file_id, required="read")
    if node.is_folder:
        raise ApiError("文件夹暂不支持打包下载", code=3203)
    path = file_service.storage_service.open_physical(node.save_path)
    if not path.is_file():
        raise ApiError("物理文件已丢失", code=3204, http_status=410)

    db.session.add(
        DownloadLog(
            user_id=current_user().id,
            file_id=node.id,
            share_id=None,
            ip=request.remote_addr,
            user_agent=(request.user_agent.string or "")[:500],
        )
    )
    db.session.commit()

    response = send_file(
        path,
        as_attachment=True,
        download_name=node.file_name,
        conditional=True,
    )
    return response


@bp.post("/folder/create")
@login_required
def create_folder():
    data = request.get_json(silent=True) or {}
    raw_parent = data.get("parent_id")
    parent_id = int(raw_parent) if raw_parent else None
    raw_dept = data.get("department_id")
    department_id = int(raw_dept) if raw_dept else None
    folder = file_service.create_folder(
        current_user(), parent_id, data.get("file_name", ""),
        department_id=department_id,
    )
    return success(folder.to_dict(), msg="文件夹创建成功")


@bp.put("/file/rename")
@login_required
def rename():
    data = request.get_json(silent=True) or {}
    node = file_service.rename_node(
        current_user(), int(data.get("id") or 0), data.get("file_name", "")
    )
    return success(node.to_dict(), msg="重命名成功")


@bp.put("/file/move")
@login_required
def move():
    data = request.get_json(silent=True) or {}
    raw_target = data.get("target_parent_id")
    target_id = int(raw_target) if raw_target else None
    node = file_service.move_node(
        current_user(), int(data.get("id") or 0), target_id
    )
    return success(node.to_dict(), msg="移动成功")


@bp.delete("/file/delete")
@login_required
def delete():
    data = request.get_json(silent=True) or {}
    file_id = int(data.get("id") or request.args.get("id") or 0)
    file_service.delete_node(current_user(), file_id)
    return success(msg="删除成功")


# ==================== 1.3.0 回收站 ====================

@bp.get("/file/trash")
@login_required
def trash_list():
    scope = request.args.get("scope", "personal")
    dept_raw = request.args.get("department_id")
    department_id = int(dept_raw) if dept_raw else None
    from ..services import trash_service

    return success({"items": trash_service.list_trash(
        current_user(), scope, department_id
    )})


@bp.post("/file/trash/restore")
@login_required
def trash_restore():
    data = request.get_json(silent=True) or {}
    from ..services import trash_service

    node = trash_service.restore(current_user(), int(data.get("id") or 0))
    return success(node.to_dict(), msg="还原成功")


@bp.delete("/file/trash/item")
@login_required
def trash_purge_one():
    data = request.get_json(silent=True) or {}
    trash_id = int(data.get("id") or request.args.get("id") or 0)
    from ..services import trash_service

    trash_service.purge_item(current_user(), trash_id)
    return success(msg="已彻底删除")


@bp.delete("/file/trash")
@login_required
def trash_empty():
    scope = request.args.get("scope", "personal")
    dept_raw = request.args.get("department_id")
    department_id = int(dept_raw) if dept_raw else None
    from ..services import trash_service

    count = trash_service.empty_trash(current_user(), scope, department_id)
    return success({"count": count}, msg=f"已清空 {count} 项")


# ==================== 1.3.0 历史版本 ====================

@bp.get("/file/versions/<int:node_id>")
@login_required
def version_list(node_id):
    from ..services import version_service

    node = file_service.get_owned_node(current_user(), node_id, required="read")
    return success({
        "current": {
            "file_hash": node.file_hash,
            "file_size": node.file_size,
            "upload_time": node.upload_time.isoformat() if node.upload_time else None,
        },
        "items": version_service.list_versions(node),
    })


@bp.get("/file/version/download")
@login_required
def version_download():
    version_id = request.args.get("version_id", type=int)
    if not version_id:
        raise ApiError("缺少版本 id", code=3513)
    from ..services import version_service

    version, node = version_service.get_version_for_access(
        current_user(), version_id, required="read"
    )
    path = file_service.storage_service.open_physical(version.save_path)
    if not path.is_file():
        raise ApiError("历史版本物理文件已丢失", code=3514, http_status=410)

    stamp = version.create_time.strftime("%Y%m%d-%H%M%S") if version.create_time else "old"
    if "." in node.file_name:
        idx = node.file_name.rfind(".")
        download_name = f"{node.file_name[:idx]}_{stamp}{node.file_name[idx:]}"
    else:
        download_name = f"{node.file_name}_{stamp}"

    return send_file(
        path,
        as_attachment=True,
        download_name=download_name,
        conditional=True,
    )


@bp.post("/file/version/restore")
@login_required
def version_restore():
    data = request.get_json(silent=True) or {}
    from ..services import version_service

    node = version_service.restore_version(
        current_user(), int(data.get("version_id") or 0)
    )
    return success(node.to_dict(), msg="版本已恢复")
