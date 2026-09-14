"""安装向导接口：状态查询、环境检测、数据库测试、执行安装。"""
from flask import Blueprint, current_app, request

from ..config import ZHY_VERSION
from ..services import setup_service
from ..utils.errors import ApiError
from ..utils.response import success

bp = Blueprint("setup", __name__, url_prefix="/api/setup")


@bp.get("/status")
def status():
    """查询安装状态（无需鉴权）。"""
    return success(
        {"installed": setup_service.is_installed(), "version": ZHY_VERSION}
    )


@bp.get("/environment")
def environment():
    """环境检测（仅未安装时可用）。"""
    _ensure_not_installed()
    info = setup_service.get_environment_info(
        request.args.get("storage_dir") or None
    )
    return success(info)


@bp.post("/test-db")
def test_db():
    """测试数据库连接与写权限（仅未安装时可用）。"""
    _ensure_not_installed()
    payload = request.get_json(silent=True) or {}
    # 支持直连 DSN
    if payload.get("database_uri"):
        uri = payload["database_uri"]
        db_type = setup_service._db_type_of_uri(uri)
    else:
        uri, db_type, _ = setup_service.build_database_uri(payload)
    setup_service.test_database(db_type, uri)
    return success({"db_type": db_type}, msg="数据库连接正常")


@bp.post("/install")
def install():
    """执行安装：写配置、建表、创建超级管理员（仅未安装时可调用一次）。"""
    _ensure_not_installed()
    payload = request.get_json(silent=True) or {}
    result = setup_service.run_installation(current_app, payload)
    return success(result, msg="安装完成")


def _ensure_not_installed() -> None:
    if setup_service.is_installed():
        raise ApiError("系统已安装，安装向导已锁定", code=2020, http_status=403)
