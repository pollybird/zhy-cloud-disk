"""内置插件：视频预览（占位实现）。

声明支持的视频后缀并挂载预览入口；前端按 preview_type=video
以 <video> 渲染 /api/plugin/file/stream 流（支持 Range 拖动）。
"""
from app.plugins.base import BasePlugin


class VideoPreviewPlugin(BasePlugin):
    name = "video-preview"
    version = "1.0.0"
    author = "zhyCloudDisk"
    description = "视频在线预览：支持 mp4/webm/mov"
    supported_exts = ("mp4", "webm", "mov")
    preview_type = "video"


plugin = VideoPreviewPlugin()
