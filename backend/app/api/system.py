"""系统信息接口：功能开关查询。"""
from flask import Blueprint, current_app

from ..utils.decorators import login_required
from ..utils.response import success

bp = Blueprint("system", __name__, url_prefix="/api/system")


@bp.get("/feature-flags")
@login_required
def feature_flags():
    """返回当前系统开启的功能模块。"""
    return success({
        "department_drive": current_app.config.get("DEPARTMENT_DRIVE_ENABLED", False),
    })
