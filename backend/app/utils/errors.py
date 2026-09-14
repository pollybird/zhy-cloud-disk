"""业务异常与全局错误处理。"""
from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from .response import fail


class ApiError(Exception):
    """业务异常基类，返回统一响应结构。"""

    def __init__(self, msg: str, code: int = 1, http_status: int = 400, data=None):
        super().__init__(msg)
        self.msg = msg
        self.code = code
        self.http_status = http_status
        self.data = data


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(e: ApiError):
        return fail(e.msg, code=e.code, http_status=e.http_status, data=e.data)

    @app.errorhandler(404)
    def _handle_404(e):
        from flask import request

        if request.path.startswith("/api/"):
            return fail("资源不存在", code=4040, http_status=404)
        return e

    @app.errorhandler(405)
    def _handle_405(e):
        return fail("请求方法不被允许", code=4050, http_status=405)

    @app.errorhandler(413)
    def _handle_413(e):
        max_size = app.config.get("MAX_UPLOAD_SIZE", 0)
        return fail(
            f"上传文件超过大小限制（{_format_size(max_size)}）",
            code=4130,
            http_status=413,
        )

    @app.errorhandler(HTTPException)
    def _handle_http_exception(e: HTTPException):
        return fail(e.description or e.name, code=e.code * 10, http_status=e.code)

    @app.errorhandler(Exception)
    def _handle_unexpected(e: Exception):
        app.logger.exception("未处理异常: %s", e)
        return fail("服务器内部错误", code=5000, http_status=500)

    _register_jwt_handlers(app)


def _register_jwt_handlers(app: Flask) -> None:
    from flask_jwt_extended import JWTManager

    # 扩展已在工厂中初始化，这里通过扩展实例注册回调
    from ..extensions import jwt

    @jwt.expired_token_loader
    def _expired_token(jwt_header, jwt_payload):
        return fail("登录已过期，请重新登录", code=4011, http_status=401)

    @jwt.invalid_token_loader
    def _invalid_token(reason):
        return fail("无效的登录凭证", code=4012, http_status=401)

    @jwt.unauthorized_loader
    def _missing_token(reason):
        return fail("请先登录", code=4010, http_status=401)

    @jwt.revoked_token_loader
    def _revoked_token(jwt_header, jwt_payload):
        return fail("登录状态已失效，请重新登录", code=4013, http_status=401)


def _format_size(num: int) -> str:
    try:
        num = float(num)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.1f}{unit}"
        num /= 1024.0
    return f"{num:.1f}PB"
