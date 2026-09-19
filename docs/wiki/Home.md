# 钟毓私有云盘（zhyCloudDisk）Wiki

本 Wiki 是 zhyCloudDisk 的完整文档集，覆盖安装部署、三端（Web / 桌面客户端 / API）使用说明、配置参考、备份恢复与开发者指南。内容基于 **v1.3.1** 源码核实编写，与 README、CHANGELOG 保持一致并做更详细的展开。

基于 **Flask + Vue3 + Electron** 的轻量私有云盘系统：服务端支持个人文件管理、分享、插件扩展与多级部门共享网盘，并提供跨平台桌面同步客户端，本地文件夹与云端实时双向同步。

> 当前版本 **v1.3.1** · Apache License 2.0 · 泰州姜堰钟毓信息技术有限公司

- 仓库：[Gitee](https://gitee.com/pollybird/zhy-cloud-disk)（主）｜ [GitHub](https://github.com/pollybird/zhy-cloud-disk) ｜ [GitCode](https://gitcode.com/pollybird/ZhyCloudDisk)
- 镜像：[Docker Hub `pollybird/zhy-cloud-disk`](https://hub.docker.com/r/pollybird/zhy-cloud-disk)（`latest` / `1.3.1` / `1.3.0` / `1.2.0`）

## 本页内容

- [特性亮点总览](#特性亮点总览)
- [快速开始](#快速开始)
- [全站导航](#全站导航)
- [版本演进速览](#版本演进速览)

---

## 特性亮点总览

| 领域 | 能力 |
|------|------|
| 个人网盘 | 文件/文件夹上传下载、重命名、移动、删除、分类检索、容量配额 |
| 跨用户秒传 | MD5+大小全局指纹库，同一文件全服务器仅存一份物理副本，按引用计数回收 |
| 分片与断点续传 | >20MB 自动 5MB 分片（并发 3、单片重试 3 次）、会话 24h 断点恢复、双 MD5 校验；下载支持 HTTP Range（206） |
| 分享 | 分享码访问、可选密码、有效期（永久/1/7/30 天）、浏览计数、下载日志 |
| 多级部门共享网盘 | 无限级部门树、成员三级权限（只读/读写/拒绝）、文件夹级授权与到期、部门管理员委派、部门配额、审计日志 |
| 排他编辑锁 | 桌面客户端打开部门文件自动加锁，TTL 2 分钟 + 30s 心跳，保存回传即释放，崩溃自动过期 |
| 回收站 | 个人盘/部门盘独立，默认保留 30 天，还原/彻底删除/清空，定时清理 |
| 文件历史版本 | 覆盖上传自动留版本，默认每文件 10 版/30 天，可下载/一键恢复，blob 引用计数不重复占盘 |
| 监控仪表盘 | CPU（cgroup v1/v2 配额识别）/内存/磁盘、5 分钟在线人数、今日与 7 天流量、存储统计 |
| 备份恢复 | 手动+每日定时；本地/远端（SFTP/FTP）目标；manifest.json + SHA-256；恢复前自动快照；恢复后 2s 自动重启 |
| 桌面客户端 | 四步向导、全量首同步、实时双向同步（chokidar + 轮询）、秒传/分片续传、托盘常驻、JWT 密钥环加密 |
| 插件扩展 | 内置图片/视频/文档预览插件，支持外部插件目录与注册/启停管理 |

## 快速开始

### 方式一：Docker 一键脚本（推荐）

```bash
git clone https://gitee.com/pollybird/zhy-cloud-disk.git && cd zhyCloudDisk
./deploy.sh init    # 生成 .env，修改管理员密码、端口等
./deploy.sh up      # 构建启动 + 自动健康检查
```

### 方式二：直接使用 Docker Hub 镜像（无需构建）

```bash
docker run -d \
  --name zhy-cloud-disk \
  -p 8080:80 \
  -e ZHY_ADMIN_USERNAME=admin \
  -e ZHY_ADMIN_PASSWORD=Admin12345 \
  -v zhy-instance:/app/instance \
  -v zhy-storage:/app/storage \
  -v zhy-mysql:/var/lib/mysql \
  pollybird/zhy-cloud-disk:latest
```

### 方式三：手动部署（无 Docker）

```bash
# 后端
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ZHY_INSTANCE_DIR=./instance ZHY_STORAGE_DIR=./storage
python run.py                        # 开发；生产用 gunicorn -w 4 -b 0.0.0.0:5000 wsgi:application

# 前端
cd frontend && npm install && npm run build   # dist/ 交给 nginx 托管，/api/ 反代到后端
```

首次启动访问 Web 地址即进入安装向导；健康检查接口 `GET /api/ping` 返回 `{code:0, data:{version, installed}}`。

> 桌面客户端连接：服务器地址直接填 Web 访问地址（如 `http://<服务器IP>:8080`），**无需带 `/api`**。详见 [桌面客户端](./04-Desktop-Client.md)。

## 适用场景

| 场景 | 推荐组合 |
|------|----------|
| 个人/家庭私有网盘 | Docker 单容器 + SQLite 思路的最小配置（镜像内置 MySQL 开箱即用），开启回收站与历史版本 |
| 中小企业团队空间 | 部门共享网盘 + 部门配额 + 审计日志 + 每日定时备份（远端 SFTP） |
| 跨地域文件协作 | 桌面同步客户端双向同步 + 分片断点续传 + 排他编辑锁防覆盖 |
| 文件对外分发 | 分享外链（可选密码、1/7/30 天有效期）+ 下载审计 |
| 运维可观测 | 监控仪表盘（CPU/内存/磁盘/在线/流量）+ 备份恢复 + pre-restore 回滚快照 |

## 全站导航

| 页面 | 内容 |
|------|------|
| [安装部署](./01-Installation.md) | 系统要求、Docker 三种方式、数据卷持久化、手动部署、HTTPS 建议、升级流程 |
| [个人网盘使用](./02-Personal-Drive.md) | 上传下载、秒传与分片断点续传、分享、回收站、历史版本、配额 |
| [部门网盘使用](./03-Department-Drive.md) | 部门树、权限模型与矩阵、部门管理员、文件夹授权、排他编辑锁、删除保护 |
| [桌面客户端](./04-Desktop-Client.md) | 下载打包、首次向导、双向同步与冲突策略、排他锁、回收站与版本、托盘与自启 |
| [管理后台](./05-Admin-Console.md) | 用户管理、系统设置全表、监控仪表盘指标口径、插件管理 |
| [备份与恢复](./06-Backup-Restore.md) | 备份内容与限制、定时备份、本地/远端目标、四种恢复方式、pre-restore 快照 |
| [API 参考](./07-API-Reference.md) | 调用约定、按蓝图分节端点表、业务错误码总表 |
| [配置参考](./08-Configuration.md) | 环境变量全表、系统设置键全表、客户端设置、定时任务清单 |
| [架构与开发](./09-Architecture-Development.md) | 技术栈、目录结构、blob 引用计数、数据流、本地开发、测试与打包发布 |
| [常见问题](./10-FAQ.md) | 部署、客户端、锁冲突、备份恢复等 15+ 条 Q/A |
| [业务码一览](./11-Business-Codes.md) | 调用约定、按业务域全量业务码（含义/触发场景/处理建议）、按码速查总表 |

## 版本演进速览

| 版本 | 主题 | 关键能力 |
|------|------|----------|
| v1.0.0 | 首发 | 个人文件管理、分享、插件、Docker 一键部署、桌面同步客户端 |
| v1.1.0 | 多级部门共享网盘 | 部门树、三级权限、部门管理员、配额、审计日志、删除保护 |
| v1.2.0 | 秒传 + 断点续传 | 跨用户秒传、分片上传、Range 下载、排他编辑锁、all-in-one 单容器镜像 |
| v1.3.0 | 数据安全与可观测 | 回收站、历史版本、监控仪表盘、备份恢复（本地/SFTP/FTP） |
| v1.3.1 | 客户端修复 | 编辑锁残留修复、客户端回收站与历史版本、显式声明 cryptography |

完整变更见仓库 [CHANGELOG.md](https://gitee.com/pollybird/zhy-cloud-disk/blob/master/CHANGELOG.md)。

## 文档约定与术语

| 术语 | 含义 |
|------|------|
| blob | 内容寻址物理块（`storage/blobs/<hash前2位>/<hash>`），同一内容全服务器一份，按引用计数回收 |
| 秒传 | 上传前凭 MD5+大小命中指纹库直接建引用，零上传流量 |
| 分片会话 | >20MB 文件上传的暂存上下文（24h 有效），支持断点续传 |
| 排他编辑锁 | 部门文件编辑互斥锁（TTL 2 分钟 + 30s 心跳） |
| pre-restore 快照 | 恢复备份前自动留存的当前数据库回滚副本 |
| 业务码 | 统一响应 `{code,msg,data}` 中 `code≠0` 的业务错误编号，见 [API 参考 · 错误码总表](./07-API-Reference.md#业务错误码总表) |

文档约定：

- 各页开头有「本页内容」锚点目录，章节间使用相对链接互跳；
- 命令默认在项目根目录执行；Docker 部署默认以 `deploy.sh` / `docker compose` 为准；
- 所有接口与错误码均以 v1.3.1 后端代码实际实现为准。

## 高频入口

| 我想要… | 去这里 |
|---------|--------|
| 最快跑起来 | [安装部署 · 一键脚本](./01-Installation.md#方式一一键脚本部署推荐) |
| 客户端连不上服务器 | [FAQ · Q6](./10-FAQ.md#q6客户端服务器地址填什么要加-api-吗) |
| 了解秒传为什么还占配额 | [FAQ · Q11](./10-FAQ.md#q11秒传是别人传过我就不用传了那我的空间还扣吗) |
| 配置每日自动备份 | [备份与恢复 · 手动与定时备份](./06-Backup-Restore.md#手动与定时备份) |
| 查接口与错误码 | [API 参考](./07-API-Reference.md) |
| 改配额/上传上限等参数 | [配置参考](./08-Configuration.md) |
| 二次开发 / 跑测试 / 打包 | [架构与开发](./09-Architecture-Development.md) |

## 阅读建议

- **普通用户**：读 [个人网盘使用](./02-Personal-Drive.md)、[部门网盘使用](./03-Department-Drive.md)、[桌面客户端](./04-Desktop-Client.md) 即可覆盖日常操作，遇到问题先查 [FAQ](./10-FAQ.md)。
- **管理员**：重点看 [管理后台](./05-Admin-Console.md) 与 [备份与恢复](./06-Backup-Restore.md)，并按 [配置参考](./08-Configuration.md) 核对环境变量与设置项的生效时机（不少变量仅首次安装生效）。
- **开发者/运维**：[架构与开发](./09-Architecture-Development.md) 给出目录结构、数据流与测试/打包流程；接口对接直接查 [API 参考](./07-API-Reference.md)。

## 反馈与贡献

- 问题反馈与功能建议：请通过 [Gitee Issues](https://gitee.com/pollybird/zhy-cloud-disk/issues) 提交，附上版本号（`/api/ping` 可查）与复现步骤；
- 代码贡献：遵循 Apache License 2.0，提交前请跑通三端测试（后端 pytest / 前端与客户端 vitest，见 [架构与开发 · 测试套件](./09-Architecture-Development.md#测试套件)）；
- 外部插件开发：见仓库 [PLUGIN_DEVELOPMENT.md](https://gitee.com/pollybird/zhy-cloud-disk/blob/master/PLUGIN_DEVELOPMENT.md)。