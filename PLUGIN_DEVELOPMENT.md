# zhyCloudDisk 插件开发规范

插件化架构允许在不修改核心代码的前提下扩展文件的预览与处理能力。插件与主进程**同进程运行**，因此安全信任边界为：**仅管理员可安装、启用插件**。插件代码应视为受信代码对待。

## 1. 快速开始

一个最小插件只需一个 `.py` 文件，放入项目根目录的 `plugins/` 即可（也支持目录包形式）：

```python
# plugins/hello_preview.py
from app.plugins.base import BasePlugin


class HelloPreviewPlugin(BasePlugin):
    name = "hello-preview"          # 全局唯一，小写字母/数字/连字符
    version = "1.0.0"
    author = "you"
    description = "示例插件"
    supported_exts = ("txt", "md")   # 支持的文件后缀（小写、不带点）
    preview_type = "text"            # 前端渲染类型


plugin = HelloPreviewPlugin()        # 模块级导出实例（或定义 get_plugin() 工厂）
```

放置后以管理员身份进入「插件管理」→「重新扫描」（或调用 `POST /api/plugin/register`），插件即出现在注册表中。外部插件**默认禁用**，需手动启用。

## 2. 插件的发现与加载

| 项目 | 说明 |
| --- | --- |
| 内置目录 | `backend/app/plugins/builtin/`（随系统发布，默认启用） |
| 外部目录 | 项目根 `plugins/`（单文件 `.py` 或含 `__init__.py` 的包） |
| 导出约定 | 模块级 `plugin` 实例，或 `get_plugin()` 工厂函数；否则取模块内首个 `BasePlugin` 子类 |
| 冲突检测 | 同名插件以先发现者为准（内置优先），后者跳过并记录扫描错误 |
| 异常隔离 | 单个插件加载失败不影响主进程与其它插件，错误写入注册表 `last_error` |
| 状态持久化 | 启用/禁用状态存于数据库 `plugin` 表，重启不丢失；源码被移除的插件记录自动清理 |

导入约定：插件以独立模块方式加载（无包上下文），**必须使用绝对导入**，例如 `from app.plugins.base import BasePlugin`；不得使用相对导入。

## 3. BasePlugin 规范

```python
from flask import Blueprint

from app.plugins.base import BasePlugin


class MyPlugin(BasePlugin):
    # ---- 元信息 ----
    name: str                  # 必填，2-63 位小写字母/数字/连字符，全局唯一
    version: str = "0.1.0"
    author: str = ""
    description: str = ""
    supported_exts: tuple = () # 小写后缀，自动去重/去点
    preview_type: str = "none" # none / image / video / pdf / text / iframe

    # ---- 生命周期钩子（按需覆写） ----
    def register(self, app) -> None:
        """启用加载时调用：初始化资源、连接外部服务等。"""

    def create_blueprint(self) -> Blueprint | None:
        """可选：返回自定义蓝图，由管理器挂载到 /api/plugin/ext/<name>。
        路由内第一行应调用 self.require_enabled() 实现禁用拦截。"""
        return None

    def unload(self) -> None:
        """禁用/重载时调用：释放连接、线程等资源。"""

    # ---- 权限钩子 ----
    def check_permission(self, user, node, action: str) -> bool:
        """通用插件 API 访问文件时的二次裁决。
        网关已保证：owner 身份只能触达自己的文件；share 身份只能触达有效分享的文件。
        action 取值：stream（读流）/ save（保存）。
        返回 False 将向调用方返回 403。默认放行。"""
        return True
```

### 3.1 preview_type 与前端渲染

前端预览挂载点按 `preview_type` 选择渲染器：

| preview_type | 渲染方式 | 适用场景 |
| --- | --- | --- |
| `image` | `<img>` | jpg / png / gif / webp 等 |
| `video` | `<video controls>`（支持 Range 拖动） | mp4 / webm 等 |
| `pdf` | `<iframe>` | pdf |
| `text` | 拉取流解码后 `<pre>` | txt / md / csv |
| `iframe` | 内嵌 iframe（预留） | 自包含 H5 页面 |
| `none` | 不渲染（仅注册声明） | 占位、后台处理型插件 |

`meta()` 返回值可被覆写以携带扩展字段：内置文档插件通过 `ext_preview` 字典按后缀细化渲染类型（如 `{"pdf": "pdf", "txt": "text"}`），前端优先取 `ext_preview[后缀]`。

## 4. 通用插件 API

插件前端视图（或第三方前端）统一通过以下接口读写文件，系统在此层完成身份与归属鉴权：

### 4.1 文件流读取

```
GET /api/plugin/file/stream?id=<文件ID>&plugin=<插件名>          # 归属用户（JWT）
GET /api/plugin/file/stream?code=<分享码>&token=<访问令牌>&plugin=<插件名>  # 分享访客
```

- 内联输出（非附件），支持 `Range` 请求（视频拖动进度）。
- `id` 与 `code+token` 二选一；归属访问需 `Authorization: Bearer <access_token>`。
- 带 `Range` 头的请求不写下载日志，避免视频 seek 刷日志。
- `plugin` 参数可选：传入时校验插件已启用、支持该后缀，并执行其 `check_permission` 钩子。

### 4.2 编辑保存

```
POST /api/plugin/file/save        # 仅归属用户
Content-Type: application/json    {"id": 123, "content": "文本内容"}
或 multipart/form-data            id=123, file=<二进制>
```

保存会重新执行类型校验（黑名单后缀拒绝）与配额校验（原子扣减增量，超额返回 413），并以「临时文件 + 原子替换」覆盖物理文件。返回更新后的文件元信息。

### 4.3 权限校验

```
GET /api/plugin/auth/check?id=<文件ID>            # 归属用户
GET /api/plugin/auth/check?code=<分享码>&token=<令牌>  # 分享访客
```

返回：

```json
{
  "allowed": true,
  "access": "owner | share",
  "file": {"id": 1, "file_name": "a.png", "file_suffix": "png", "file_size": 123, "is_folder": false},
  "user": "admin",
  "plugins": [{"name": "image-preview", "preview_type": "image", "...": "..."}]
}
```

`plugins` 为该后缀当前**已启用**的插件列表，前端据此选择渲染器。

### 4.4 按后缀查询插件（归属用户）

```
GET /api/plugin/available?suffix=jpg
```

### 4.5 插件自定义路由

插件返回的蓝图挂载在 `/api/plugin/ext/<插件名>/...`。示例：

```python
def create_blueprint(self):
    bp = Blueprint("my-plugin", __name__)

    @bp.get("/stats")
    def stats():
        self.require_enabled()  # 禁用时返回 403
        return {"ok": True}

    return bp
```

注意：Flask 不支持注销蓝图，禁用语义由 `require_enabled()` 在请求时拦截。

## 5. 管理接口（仅管理员）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/plugin/list` | 注册表列表 + 已加载名 + 扫描错误 |
| PUT | `/api/plugin/<name>/enabled` | `{"enabled": true/false}` 启停 |
| POST | `/api/plugin/register` | 重扫描并同步注册表；`{"name": "x"}` 可顺带启用 |

## 6. 打包与投放

- 单文件：`plugins/<你的插件>.py`。
- 目录包：`plugins/<your_plugin>/__init__.py`（可在包内拆分多模块）。
- 版本升级：覆盖源码后在管理页「重新扫描」，注册表自动更新元信息，启用状态保留。
- 卸载：移除源码 →「重新扫描」→ 注册表记录自动清理。
- 依赖：插件如需第三方库，需自行在部署环境安装（`backend/requirements.txt` 管理核心依赖）。

## 7. 安全约定

1. **信任边界**：插件与主进程同进程运行，具备全部后端能力；只安装来源可信的插件。
2. **鉴权不绕过**：插件读取文件必须走通用插件 API 或在自定义路由中复用 `login_required`/归属校验，不得自行信任前端参数。
3. **路径安全**：操作物理文件一律经 `storage_service.open_physical()` 校验，防止路径穿越。
4. **失败隔离**：`register()` 内的异常会导致插件启用失败并记录错误，主进程不受影响；`unload()` 中的异常仅记录日志。
