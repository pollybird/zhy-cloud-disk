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
