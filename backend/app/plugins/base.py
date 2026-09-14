"""BasePlugin：插件抽象规范。

插件以"声明式元信息 + 可选钩子"的形式接入主系统：
- 元信息：name/version/author/description/supported_exts/preview_type
- 生命周期：register(app) 加载入口 →（可选）create_blueprint() 提供自定义路由 → unload() 释放资源
- 权限：插件 API 网关统一完成身份与归属鉴权后，再调用 check_permission 钩子供插件二次裁决

安全前提：插件与主进程同进程运行，信任边界为"仅管理员可安装/启用"。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import Blueprint, Flask

if TYPE_CHECKING:  # pragma: no cover
    from ..models.file_node import FileNode
    from ..models.user import User

# 允许的预览渲染类型（前端按此映射渲染器）
PREVIEW_TYPES = {"none", "image", "video", "pdf", "text", "iframe"}


class PluginMetaError(Exception):
    """插件元信息不合法。"""


class BasePlugin:
    """所有插件必须继承本类并在模块级提供实例（变量名 plugin）或 get_plugin() 工厂。"""

    # ---- 元信息（子类必须覆写 name） ----
    name: str = ""
    version: str = "0.1.0"
    author: str = ""
    description: str = ""
    # 支持的文件后缀（小写、不带点），如 ("jpg", "png")
    supported_exts: tuple[str, ...] = ()
    # 前端预览渲染类型，见 PREVIEW_TYPES
    preview_type: str = "none"

    def __init__(self) -> None:
        self.validate_meta()

    # ------------------------------------------------------------------
    # 元信息校验
    # ------------------------------------------------------------------
    def validate_meta(self) -> None:
        import re

        if not self.name or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", self.name):
            raise PluginMetaError(
                f"插件 name 不合法：{self.name!r}（需 2-63 位小写字母/数字/连字符）"
            )
        if self.preview_type not in PREVIEW_TYPES:
            raise PluginMetaError(
                f"插件 {self.name} 的 preview_type 必须是 {sorted(PREVIEW_TYPES)} 之一"
            )
        if not isinstance(self.supported_exts, tuple):
            self.supported_exts = tuple(self.supported_exts or ())
        cleaned = []
        for ext in self.supported_exts:
            ext = str(ext).lower().lstrip(".")
            if ext and ext not in cleaned:
                cleaned.append(ext)
        self.supported_exts = tuple(cleaned)

    def meta(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "supported_exts": list(self.supported_exts),
            "preview_type": self.preview_type,
        }

    # ------------------------------------------------------------------
    # 生命周期钩子（子类按需覆写）
    # ------------------------------------------------------------------
    def register(self, app: Flask) -> None:
        """插件被启用加载时的入口：可做初始化、注册扩展等。默认无操作。"""

    def create_blueprint(self) -> Blueprint | None:
        """可选：返回插件自定义蓝图（url_prefix 由管理器统一挂到 /api/plugin/ext/<name>）。

        注意：Flask 不支持注销蓝图，禁用语义由管理器在网关层拦截——
        插件自定义路由的第一行应调用 self.require_enabled()。
        """
        return None

    def unload(self) -> None:
        """插件被禁用/卸载时释放资源。默认无操作。"""

    # ------------------------------------------------------------------
    # 权限钩子
    # ------------------------------------------------------------------
    def check_permission(self, user: "User | None", node: "FileNode", action: str) -> bool:
        """通用插件 API 调用文件时的二次权限裁决。

        - 网关已保证：登录用户只能触达自己的文件；分享访客只能触达有效分享的文件。
        - 插件可按需收紧（如某些 action 仅限 owner）。默认放行。
        """
        return True

    # ------------------------------------------------------------------
    # 插件自定义路由使用的工具
    # ------------------------------------------------------------------
    def require_enabled(self) -> None:
        """插件自定义路由内调用：插件被禁用时抛出 403。"""
        from .manager import manager

        if not manager.is_enabled(self.name):
            from ..utils.errors import ApiError

            raise ApiError("插件已被禁用", code=5102, http_status=403)
