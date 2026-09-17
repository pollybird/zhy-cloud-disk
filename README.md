# 钟毓私有云盘（zhyCloudDisk）

基于 Flask + Vue3 + Electron 的轻量私有云盘系统，服务端支持个人文件管理、多级部门共享网盘、分享、插件扩展，并提供桌面同步盘客户端，本地文件夹与云端实时双向同步。

> Copyright (c) 2026 泰州姜堰钟毓信息技术有限公司. 本项目基于 [Apache License 2.0](./LICENSE) 开源。

## 仓库地址

- Gitee：<https://gitee.com/pollybird/zhy-cloud-disk>
- GitHub：<https://github.com/pollybird/zhy-cloud-disk>

## 技术栈

- **后端**：Flask 3.0 + SQLAlchemy + Flask-JWT-Extended + APScheduler + Redis（可选）
- **前端**：Vue 3 + Element Plus + Vite + Pinia
- **桌面客户端**：Electron 33 + electron-vite + Vue 3 + better-sqlite3 + chokidar
- **数据库**：SQLite（开发）/ MySQL / PostgreSQL（生产）
- **部署**：Docker Compose（gunicorn + nginx）

## Docker 一键部署

### 快速部署（推荐）

要求服务器已安装 Docker 引擎与 Compose 插件，然后执行：

```bash
git clone https://gitee.com/pollybird/zhy-cloud-disk.git && cd zhyCloudDisk

./deploy.sh init    # 首次从 .env.example 生成 .env，按需修改管理员密码、端口、部门开关等
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
| `./deploy.sh shell` | 进入后端容器（排障用） |

以下为等效的手动分步说明，适合需要逐步确认的场景。

### 1. 克隆仓库

```bash
# Gitee
git clone https://gitee.com/pollybird/zhy-cloud-disk.git && cd zhyCloudDisk

# 或 GitHub
git clone https://github.com/pollybird/zhy-cloud-disk.git && cd zhyCloudDisk
```

### 2. 配置环境变量（可选）

创建 `.env` 文件或直接在 shell 中导出：

```bash
# 超级管理员（首次启动自动初始化）
export ZHY_ADMIN_USERNAME=admin
export ZHY_ADMIN_PASSWORD=Admin12345
export ZHY_ADMIN_EMAIL=admin@example.com

# Web 访问端口
export ZHY_WEB_PORT=8080

# 部门共享网盘（仅首次静默安装生效；默认关闭，之后在系统设置中切换）
export ZHY_DEPARTMENT_DRIVE=true

# 数据库（默认 SQLite；切换 MySQL 示例）
# export ZHY_DATABASE_URL=mysql+pymysql://user:pass@db-host:3306/zhycloud

# Redis（默认指向 compose 内的 redis 服务）
# export ZHY_REDIS_URL=redis://redis:6379/0
```

### 3. 启动

```bash
docker compose up -d --build
```

首次启动时后端容器会自动执行安装向导（创建数据库表、初始化超管账号）。
访问 `http://<服务器IP>:<ZHY_WEB_PORT>` 即可使用。

> **桌面客户端如何连接**：客户端服务器地址直接填 Web 访问地址即可，例如 `http://<服务器IP>:8080`（与浏览器访问 Web 端相同，无需带 `/api` 路径或端口号）。请求经 frontend 容器的 nginx 反向代理（`/api/` → `backend:5000`）到达后端，后端容器默认不对外暴露端口。
> 如需绕过网关直连后端排障，可设环境变量 `ZHY_BACKEND_PORT=0.0.0.0:5000` 后重新 `docker compose up -d`（不设置时仅绑定宿主机回环口 `127.0.0.1:5000`）。公网部署建议在前面增加 HTTPS 反向代理，客户端使用 `https://` 地址。

### 4. 常用命令

```bash
# 查看日志
docker compose logs -f backend

# 重启
docker compose restart

# 停止
docker compose down

# 升级（拉取新代码后）
docker compose up -d --build
```

### 5. 数据持久化

| Volume | 容器路径 | 用途 |
|--------|----------|------|
| `backend-instance` | `/app/instance` | SQLite 数据库、安装配置 |
| `backend-storage` | `/app/storage` | 用户上传文件 |
| `redis-data` | `/data` | Redis 持久化 |

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

## 桌面同步客户端（client/）

跨平台桌面客户端（Windows / macOS / Linux），将本地指定文件夹与云盘实时双向同步。

### 功能特性

- **首次运行向导**：服务器地址（含连通性测试）→ 账号密码 → 本地同步路径 → 开机自启，四步完成配置
- **首次全量同步**：自动将云端全部文件（含多级目录）下载到本地同步文件夹
- **实时双向同步**：
  - 本地增 / 删 / 改 / 重命名 / 移动 → 自动上传到服务器（chokidar 监听，重命名与移动智能配对，不误判成删除+重传）
  - 服务器端变更 → 定时轮询（默认 60s）拉取并同步到本地
- **秒传去重**：上传前基于 MD5 预检，内容一致自动跳过；同名不同内容按策略处理冲突
- **主界面同步历史**：全部记录 / 已同步 / 失败 三个标签页，实时显示每个文件的下载、上传、删除、改名、移动记录及失败原因
- **常驻托盘**：关闭主界面驻留系统托盘继续同步，右键托盘菜单可打开主界面、打开同步文件夹、立即同步、设置开机自启、退出
- **安全存储**：JWT 通过系统密钥环加密保存（safeStorage / Keychain / DPAPI），401 自动刷新 token
- **冲突策略**：保留两者（自动生成"服务器冲突"副本）或最后修改者胜出
- **部门网盘（v1.1.0）**：按权限浏览可见部门树与文件；双击下载到临时目录调用本机程序打开，编辑保存后自动回传（读写权限），另存文件不回传；支持多选下载到本地、按钮与拖拽上传到部门目录、文件夹上传；临时缓存退出清理并按超期策略回收

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
npm test             # 56 个用例（vitest）
npm run test:watch   # 监听模式
```

覆盖任务队列（串行/去重/退避重试）、远端 diff 协调器、路径映射、MD5 计算、HTTP 拦截器（401 自动刷新）、设置持久化、token 加密存储等核心逻辑。

### 打包发布

```bash
npm run package:linux   # Linux AppImage
npm run package:win     # Windows NSIS 安装包
npm run package:mac     # macOS DMG
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
├── tests/               # vitest 单元测试（56 用例）
└── resources/           # 应用图标
```

## 环境变量参考

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHY_INSTANCE_DIR` | `backend/instance` | 实例目录（安装配置 + SQLite） |
| `ZHY_STORAGE_DIR` | `backend/storage` | 文件存储根目录 |
| `ZHY_ADMIN_USERNAME` | — | 超管用户名（静默安装） |
| `ZHY_ADMIN_PASSWORD` | — | 超管密码（静默安装） |
| `ZHY_ADMIN_EMAIL` | — | 超管邮箱 |
| `ZHY_DATABASE_URL` | SQLite | SQLAlchemy 连接串 |
| `ZHY_REDIS_URL` | 空（内存缓存） | Redis 连接串 |
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
├── backend/
│   ├── app/
│   │   ├── api/           # 蓝图接口（auth, file, department, permission, share, plugin, setup, user）
│   │   ├── models/        # 数据模型（user, file_node, department, file_permission, share, ...）
│   │   ├── services/      # 业务逻辑（auth, file, department, permission, share, setup, cache, ...）
│   │   ├── plugins/       # 插件框架（base, manager, builtin/）
│   │   ├── tasks/         # 定时任务（过期分享清理）
│   │   └── utils/         # 工具（response, errors, security, validators, decorators）
│   ├── tests/             # pytest 测试套件（148 用例）
│   ├── wsgi.py            # gunicorn 生产入口
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── views/         # 页面（Files, Setup, Login, Register, Profile, ...）
│   │   ├── components/    # 组件（PluginPreview, FileUploadDialog, ...）
│   │   └── stores/        # Pinia 状态管理
│   ├── Dockerfile
│   └── nginx.conf
├── client/                # Electron 桌面同步客户端
│   ├── src/
│   │   ├── main/          # 主进程（窗口 / 托盘 / 开机自启 / IPC）
│   │   ├── preload/       # contextBridge 安全桥
│   │   ├── renderer/      # Vue3 界面（向导 / 同步历史 / 设置）
│   │   └── lib/           # API 封装 / 镜像库 / 同步引擎
│   └── tests/             # vitest 单元测试（56 用例）
├── plugins/               # 外部插件目录
├── docker-compose.yml
└── README.md
```
