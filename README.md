# 钟毓私有云盘（zhyCloudDisk）

基于 Flask + Vue3 + Electron 的轻量私有云盘系统，服务端支持个人文件管理、多级部门共享网盘、分享、插件扩展，并提供桌面同步盘客户端，本地文件夹与云端实时双向同步。

> Copyright (c) 2026 泰州姜堰钟毓信息技术有限公司. 本项目基于 [Apache License 2.0](./LICENSE) 开源。

## 仓库地址

- Gitee：<https://gitee.com/pollybird/zhy-cloud-disk>
- GitHub：<https://github.com/pollybird/zhy-cloud-disk>
- GitCode：<https://gitcode.com/pollybird/ZhyCloudDisk>
- Docker Hub：<https://hub.docker.com/r/pollybird/zhy-cloud-disk>（`pollybird/zhy-cloud-disk:latest`）

## 技术栈

- **后端**：Flask 3.0 + SQLAlchemy + Flask-JWT-Extended + APScheduler + Redis（可选）
- **前端**：Vue 3 + Element Plus + Vite + Pinia
- **桌面客户端**：Electron 33 + electron-vite + Vue 3 + better-sqlite3 + chokidar
- **数据库**：SQLite（开发 / 手动部署）/ MySQL（Docker 镜像内置，也支持外部 MySQL / PostgreSQL）
- **部署**：Docker 单容器（内置 MySQL + Redis + nginx + gunicorn）

## Docker 一键部署

镜像内置 MySQL + Redis + nginx + gunicorn，单容器即可运行，无需单独配置数据库。

### 方式一：一键脚本部署（推荐）

要求服务器已安装 Docker 引擎与 Compose 插件：

```bash
git clone https://gitee.com/pollybird/zhy-cloud-disk.git && cd zhyCloudDisk

./deploy.sh init    # 首次从 .env.example 生成 .env，按需修改管理员密码、端口等
./deploy.sh up      # 构建镜像、后台启动，并自动轮询 /api/ping 做健康检查
```

部署脚本 [deploy.sh](./deploy.sh) 常用命令：

| 命令 | 说明 |
|------|------|
| `./deploy.sh init` | 生成 `.env`（已存在则跳过），所有变量说明见 [.env.example](./.env.example) |
| `./deploy.sh up` | 构建并启动（默认命令），完成后输出 Web 与客户端访问地址 |
| `./deploy.sh down` | 停止并移除容器（数据卷保留） |
| `./deploy.sh restart` | 重启服务并重新健康检查 |
| `./deploy.sh status` | 查看容器状态 |
| `./deploy.sh logs` | 跟踪全部服务日志 |
| `./deploy.sh update` | 拉取最新代码后重新构建并滚动更新 |
| `./deploy.sh shell` | 进入容器（排障用） |

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

首次启动自动完成安装（创建 MySQL 数据库、建表、初始化超管账号），访问 `http://<服务器IP>:8080` 即可使用。

### 方式三：手动分步部署

```bash
# 1. 克隆仓库
git clone https://gitee.com/pollybird/zhy-cloud-disk.git && cd zhyCloudDisk

# 2. 配置环境变量（可选，不配置则使用默认值）
cp .env.example .env
# 编辑 .env，修改管理员密码 ZHY_ADMIN_PASSWORD、端口 ZHY_WEB_PORT 等

# 3. 构建并启动
docker compose up -d --build
```

首次启动时容器自动执行静默安装（创建 MySQL 数据库与超管账号）。访问 `http://<服务器IP>:<ZHY_WEB_PORT>` 即可使用。

> **桌面客户端如何连接**：客户端服务器地址直接填 Web 访问地址即可，例如 `http://<服务器IP>:8080`（与浏览器访问 Web 端相同，无需带 `/api` 路径）。请求经容器内 nginx 反向代理（`/api/` → `127.0.0.1:5000`）到达后端。
> 公网部署建议在前面增加 HTTPS 反向代理，客户端使用 `https://` 地址。

### 常用命令

```bash
# 查看日志
docker compose logs -f app

# 重启
docker compose restart

# 停止（数据卷保留）
docker compose down

# 升级（拉取新代码后）
docker compose up -d --build
```

### 数据持久化

| Volume | 容器路径 | 用途 |
|--------|----------|------|
| `app-instance` | `/app/instance` | 安装配置 |
| `app-storage` | `/app/storage` | 用户上传文件 |
| `app-mysql` | `/var/lib/mysql` | MySQL 数据 |

## 手动部署（无 Docker）

### 后端

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 设置环境变量
export ZHY_INSTANCE_DIR=./instance
export ZHY_STORAGE_DIR=./storage

# 开发模式
python run.py

# 生产模式
gunicorn -w 4 -b 0.0.0.0:5000 wsgi:application
```

首次启动访问 `http://localhost:5000` 会进入安装向导页面，按提示完成初始化。

### 前端

```bash
cd frontend
npm install
npm run dev    # 开发
npm run build  # 生产构建，输出到 dist/
```

生产环境用 nginx 托管 `dist/` 并将 `/api/` 反向代理到后端 5000 端口。

## 多级部门共享网盘（v1.1.0）

面向团队的共享空间，与个人网盘物理目录、配额、权限完全隔离。

- **无限级部门树**：超管可新增 / 重命名 / 迁移 / 删除部门，设置部门显示排序与独立存储配额（`0` 表示不限额）。
- **成员与授权**：部门成员默认只读；可显式授予 `read_only` / `read_write` / `denied` 权限，支持文件夹级授权与到期时间；可委派部门管理员（仅本部门 / 本部门及子部门）。
- **部门文件**：上传走 MD5 秒传预检与配额原子扣减；改名、移动、文件夹递归、下载、审计日志一应俱全。
- **功能开关**：安装向导或系统设置中开启；Docker 静默安装时用环境变量 `ZHY_DEPARTMENT_DRIVE=true` 开启，默认关闭。
- **关闭时的接口行为**：部门相关接口（`/api/department/*`、`/api/permission/*`、`/api/log/*`）蓝图仍注册，但由应用级守卫统一拒绝，返回 HTTP 403、业务码 `4030`「部门网盘功能未开启」；个人网盘接口与 `/api/system/feature-flags` 不受影响（后者需登录）。
- **删除保护**：部门（含任意子孙部门）下仍存在正常文件或文件夹时，删除请求返回 HTTP 409、业务码 `3310`，请先迁移或清空文件后再删除；删除空部门会一并清理其成员、管理员与授权关联，审计日志不受影响。
- **1.0.0 升级**：旧库首次启动自动补建部门相关表与 `file_node.file_hash`、`file_node.department_id`、`user.primary_department_id` 列（幂等）；未配置开关时默认关闭，个人功能与历史数据不受影响。

## 跨用户秒传与断点续传（v1.2.0）

- **跨用户秒传**：上传前以 MD5+大小查询全局指纹库（`file_blob`），任意用户已传过同一文件则零带宽完成；物理文件全局仅存一份，按引用计数回收，各用户/部门仍正常占用各自逻辑配额。
- **分片上传**：大于 20MB 的文件自动按 5MB 分片（并发 3、单片重试 3 次）；中断后重新上传自动恢复会话、仅补传缺失分片（会话 24h 有效）；单片 MD5 与合并后整文件 MD5 双重校验。
- **Range 下载**：下载接口支持标准 HTTP Range（206），客户端中断后从 `.zhy.part` 续传，完成后校验大小与 MD5。
- **存量收敛**：每日任务自动为历史文件补算指纹并收敛重复物理副本；每 10 分钟清理过期分片会话与孤儿暂存目录。
- **部门文件排他编辑锁**：读写用户在桌面客户端打开部门文件即自动加锁，其他读写用户期间只能只读打开（文件图标显示锁角标与持有者）；保存回传成功后立即解锁，心跳续约 TTL 2 分钟、崩溃自动过期；他人持锁时覆盖/改名/移动/删除由服务端统一拒绝（业务码 `3501`）。
- **接口**：新增 `/api/file/instant`、`/api/file/chunk/init|upload|complete|abort|status` 与 `/api/file/lock/acquire|heartbeat|release|status`；`/api/file/upload` 与 `/api/file/check-duplicate` 完全向后兼容。

## 回收站 / 历史版本 / 监控 / 备份恢复（v1.3.0）

### 回收站与历史版本

- 删除文件默认进入**回收站**（个人盘与部门盘各自独立），保留 **30 天**，可按原位置还原、单条彻底删除、清空回收站；到期定时任务自动清理。
- 文件被覆盖上传时自动保留**历史版本**（默认每文件 10 个、保留 30 天），可下载旧版本或一键恢复（恢复动作自身也留版本）；物理 blob 按引用计数复用，不额外浪费磁盘。
- 两项功能在「系统管理 → 系统设置」中**独立开关**（默认均开启），关闭后不再产生新数据但**不清毁存量**；保留天数与版本数可调。

### 监控仪表盘

「系统管理 → 监控仪表盘」提供 CPU（容器内自动识别 cgroup v1/v2 配额）、内存、磁盘、5 分钟在线人数、今日与近 7 天上 / 下行流量、存储用量与对象计数（个人 / 部门占用、文件 / 文件夹 / 用户 / 部门数），支持 30 秒自动刷新。

### 备份与恢复

- 在「系统管理 → 备份恢复」中可**立即手动备份**，或在系统设置中开启**每日定时备份**并指定小时（每小时 :17 检查，改时间无需重启）与保留份数。
- 备份包内容为**数据库（元数据）+ 安装配置**，zip 包内附 `manifest.json` 与 SHA-256 校验；**不含文件实体**，文件实体请通过存储卷快照 / 磁盘备份另行保障。
- **备份目标二选一**（系统设置中配置）：
  - **本地服务器**：备份保存在服务器 `storage/backups/`。
  - **远端服务器**：支持 **SFTP（推荐）/ FTP** 协议，需填写服务器 IP / 域名、端口（SFTP 默认 22、FTP 默认 21）、用户名、密码与远端目录；密码经 **Fernet 加密**后入库，界面永不回传明文，留空提交表示不修改。可点击「测试连接」先验证再保存；远端目录不存在时自动逐级创建；上传失败自动保留本地包。
- **恢复**：可直接用服务器上的备份记录、游离本地文件、远端文件名，或在备份恢复页**上传 zip 备份包**恢复。恢复前强制勾选风险确认，恢复前自动生成 pre-restore 回滚快照；恢复成功 2 秒后进程自动退出，由 Docker（内置 supervisor）/ systemd / supervisor 守护自动拉起。
- 支持 **SQLite 与 MySQL**（含 Docker 内置 MariaDB，自动适配 `mariadb-dump` / `mysqldump`）；PostgreSQL 备份恢复暂不支持并会明确提示。
- Docker 部署建议同时备份三个数据卷：`app-mysql`（数据库）、`app-storage`（文件实体与本地备份包）、`app-instance`（安装配置）。

## 桌面同步客户端（client/）

跨平台桌面客户端（Windows / macOS / Linux），将本地指定文件夹与云盘实时双向同步。

### 功能特性

- **首次运行向导**：服务器地址（含连通性测试）→ 账号密码 → 本地同步路径 → 开机自启，四步完成配置
- **首次全量同步**：自动将云端全部文件（含多级目录）下载到本地同步文件夹
- **实时双向同步**：
  - 本地增 / 删 / 改 / 重命名 / 移动 → 自动上传到服务器（chokidar 监听，重命名与移动智能配对，不误判成删除+重传）
  - 服务器端变更 → 定时轮询（默认 60s）拉取并同步到本地
- **秒传去重**：上传前基于 MD5 预检，内容一致自动跳过；同名不同内容按策略处理冲突
- **大文件分片与断点续传（v1.2.0）**：大于 20MB 自动分片上传，中断后仅补传缺失分片；下载支持 Range 断点续传，完成后校验 MD5
- **主界面同步历史**：全部记录 / 已同步 / 失败 三个标签页，实时显示每个文件的下载、上传、删除、改名、移动记录及失败原因
- **常驻托盘**：关闭主界面驻留系统托盘继续同步，右键托盘菜单可打开主界面、打开同步文件夹、立即同步、设置开机自启、退出
- **安全存储**：JWT 通过系统密钥环加密保存（safeStorage / Keychain / DPAPI），401 自动刷新 token
- **冲突策略**：保留两者（自动生成"服务器冲突"副本）或最后修改者胜出
- **部门网盘（v1.1.0）**：按权限浏览可见部门树与文件；双击下载到临时目录调用本机程序打开，编辑保存后自动回传（读写权限），另存文件不回传；支持多选下载到本地、按钮与拖拽上传到部门目录、文件夹上传；临时缓存退出清理并按超期策略回收
- **部门文件排他锁（v1.2.0）**：打开读写文件自动抢锁，他人持锁时只读打开并提示持有者（文件图标带锁角标），保存回传后释放；心跳续约、崩溃 TTL 回收

### 安装依赖（国内镜像）

客户端已内置 `.npmrc`，自动使用 npmmirror 镜像（含 Electron 与 better-sqlite3 二进制镜像）：

```bash
cd client
npm install
```

> better-sqlite3 为原生模块，npm 会按 Electron ABI 自动编译；若提示 ABI 不匹配，执行 `npx electron-rebuild -f -w better-sqlite3`。

### 开发运行

```bash
npm run dev          # electron-vite 开发模式
# 或构建后直接运行：
npx electron-vite build
./node_modules/.bin/electron .
```

> **Linux 无 root 环境提示**：若无法为 `chrome-sandbox` 设置 SUID 权限，开发时追加参数 `--no-sandbox --disable-gpu-sandbox`。正式安装包（deb/AppImage）会自动配置沙箱，无需此参数。

### 单元测试

```bash
npm test             # 127 个用例（vitest）
npm run test:watch   # 监听模式
```

覆盖任务队列（串行/去重/退避重试）、远端 diff 协调器、路径映射、MD5 计算、HTTP 拦截器（401 自动刷新）、设置持久化、token 加密存储、分片上传 / Range 断点下载、部门文件排他锁生命周期等核心逻辑。

### 打包发布

```bash
npm run package:linux   # Linux AppImage
npm run package:win     # Windows 免安装便携版（portable exe）
npm run package:mac     # macOS zip（x64 + arm64；macOS 本机构建可改用 dmg）
```

产物输出到 `client/dist/`。

### 客户端目录结构

```
client/
├── src/
│   ├── main/            # 主进程：窗口、托盘、开机自启、IPC
│   ├── preload/         # 安全桥（contextBridge 暴露受限 API）
│   ├── renderer/        # Vue3 界面：配置向导、同步历史主界面、设置
│   └── lib/
│       ├── api/         # axios 封装（token 注入 / 401 刷新 / 文件接口）
│       ├── mirror/      # better-sqlite3 镜像库（远端树快照 / 本地指纹 / 同步日志）
│       ├── store/       # 设置持久化 + 加密 token
│       └── sync/        # 同步引擎：watcher / poller / 队列 / 协调器 / 哈希
├── tests/               # vitest 单元测试（127 用例）
└── resources/           # 应用图标
```

## 环境变量参考

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHY_DOCKER` | 0 | Docker 模式（设为 1 时使用内置 MySQL + Redis，跳过数据库配置） |
| `ZHY_INSTANCE_DIR` | `backend/instance` | 实例目录（安装配置） |
| `ZHY_STORAGE_DIR` | `backend/storage` | 文件存储根目录 |
| `ZHY_ADMIN_USERNAME` | — | 超管用户名（静默安装） |
| `ZHY_ADMIN_PASSWORD` | — | 超管密码（静默安装） |
| `ZHY_ADMIN_EMAIL` | — | 超管邮箱 |
| `ZHY_DATABASE_URL` | SQLite | SQLAlchemy 连接串（Docker 模式自动使用内置 MySQL） |
| `ZHY_REDIS_URL` | 空（内存缓存） | Redis 连接串（Docker 模式自动使用内置 Redis） |
| `ZHY_JWT_ACCESS_HOURS` | 2 | Access Token 有效期（小时） |
| `ZHY_JWT_REFRESH_DAYS` | 30 | Refresh Token 有效期（天） |
| `ZHY_DEFAULT_QUOTA` | 5368709120 | 默认用户配额（字节，5GiB） |
| `ZHY_CORS_ORIGINS` | * | CORS 允许源 |
| `ZHY_ALLOW_REGISTER` | false | 是否开放注册 |
| `ZHY_DEPARTMENT_DRIVE` | false | 静默安装时是否开启部门共享网盘（`true`/`false`，仅首次安装生效，之后在系统设置中切换） |

## 开发测试

```bash
# 后端测试
cd backend && .venv/bin/python -m pytest tests/ -v

# 前端构建
cd frontend && npm run build

# 客户端单元测试
cd client && npm test
```

## 架构概览

```
zhyCloudDisk/
├── Dockerfile             # all-in-one 镜像（内置 MySQL + Redis + nginx + gunicorn）
├── docker-compose.yml
├── deploy.sh              # 一键部署脚本
├── .env.example           # 环境变量示例
├── backend/
│   ├── app/
│   │   ├── api/           # 蓝图接口（auth, file, department, permission, share, plugin, setup, user）
│   │   ├── models/        # 数据模型（user, file_node, department, file_permission, share, ...）
│   │   ├── services/      # 业务逻辑（auth, file, department, permission, share, setup, cache, ...）
│   │   ├── plugins/       # 插件框架（base, manager, builtin/）
│   │   ├── tasks/         # 定时任务（过期分享清理、过期锁清理）
│   │   └── utils/         # 工具（response, errors, security, validators, decorators）
│   ├── tests/             # pytest 测试套件
│   ├── wsgi.py            # gunicorn 生产入口
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── views/         # 页面（Files, Setup, Login, Register, Profile, ...）
│   │   ├── components/    # 组件（PluginPreview, FileUploadDialog, ...）
│   │   └── stores/        # Pinia 状态管理
│   └── dist/              # 前端构建产物（构建镜像前需 npm run build）
├── client/                # Electron 桌面同步客户端
│   ├── src/
│   │   ├── main/          # 主进程（窗口 / 托盘 / 开机自启 / IPC）
│   │   ├── preload/       # contextBridge 安全桥
│   │   ├── renderer/      # Vue3 界面（向导 / 同步历史 / 设置）
│   │   └── lib/           # API 封装 / 镜像库 / 同步引擎
│   └── tests/             # vitest 单元测试
└── plugins/               # 外部插件目录
```
