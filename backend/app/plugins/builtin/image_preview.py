"""内置插件：图片预览（占位实现）。

声明支持的图片后缀并挂载预览入口；前端按 preview_type=image
以 <img> 渲染 /api/plugin/file/stream 流。编辑能力为后续迭代。
"""
from app.plugins.base import BasePlugin


class ImagePreviewPlugin(BasePlugin):
    name = "image-preview"
    version = "1.0.0"
    author = "zhyCloudDisk"
    description = "图片在线预览：支持 jpg/jpeg/png/gif/webp/bmp/svg"
    supported_exts = ("jpg", "jpeg", "png", "gif", "webp", "bmp", "svg")
    preview_type = "image"


plugin = ImagePreviewPlugin()
