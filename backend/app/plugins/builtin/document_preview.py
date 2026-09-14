"""内置插件：文档预览（占位实现）。

- pdf → preview_type=pdf，前端以 <iframe> 渲染
- txt/md/csv/rtf → preview_type=text，前端拉取流以文本渲染
- doc/docx/xls/xlsx/ppt/pptx → 仅注册声明（preview_type=none），
  在线编辑/转换能力为后续迭代。
"""
from app.plugins.base import BasePlugin


class DocumentPreviewPlugin(BasePlugin):
    name = "document-preview"
    version = "1.0.0"
    author = "zhyCloudDisk"
    description = "文档在线预览：pdf 直接预览，txt/md/csv 纯文本预览；Office 系列仅声明占位"
    supported_exts = ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md", "csv", "rtf")
    preview_type = "none"

    def meta(self) -> dict:
        """按具体后缀细化渲染类型，供前端选择渲染器。"""
        data = super().meta()
        data["preview_type"] = self.preview_type
        data["ext_preview"] = {
            "pdf": "pdf",
            "txt": "text",
            "md": "text",
            "csv": "text",
            "rtf": "text",
        }
        return data


plugin = DocumentPreviewPlugin()
