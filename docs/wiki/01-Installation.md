# 安装部署

本页介绍 zhyCloudDisk 的系统要求与三种部署方式（Docker 一键脚本 / 现成镜像 / 分步 compose）、数据卷持久化、无 Docker 的手动部署、桌面客户端连接方法、HTTPS 建议与升级流程。

## 本页内容

- [系统要求](#系统要求)
- [方式一：一键脚本部署（推荐）](#方式一一键脚本部署推荐)
- [方式二：直接使用 Docker Hub 镜像](#方式二直接使用-docker-hub-镜像)
- [方式三：分步 Docker Compose 部署](#方式三分步-docker-compose-部署)
- [数据卷与持久化](#数据卷与持久化)
- [手动部署（无 Docker）](#手动部署无-docker)
- [静默安装与健康检查](#静默安装与健康检查)
- [桌面客户端连接服务端](#桌面客户端连接服务端)
- [HTTPS 建议](#https-建议)
- [升级流程](#升级流程)

---

## 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | 任意支持 Docker 的 Linux 发行版（手动部署支持 Windows / macOS / Linux） |
| Docker 部署 | Docker 引擎 + Compose 插件；无需单独安装数据库 |
| 手动部署 | Python 3.10+（后端）、Node.js 18+（前端构建）、MySQL / PostgreSQL / SQLite 任一数据库 |
| 端口 | Web 端口默认 `8080`（容器内 nginx 监听 80）；后端 5000 仅绑定容器内回环 |
| 浏览器 | 现代 Chromium / Firefox / Safari |

Docker 镜像为 **all-in-one 单容器**：内置 MySQL（MariaDB 11）+ Redis + nginx + gunicorn，由 supervisor 统一托管，无需再单独部署数据库。

## 方式一：一键脚本部署（推荐）

```bash
git clone https://gitee.com/pollybird/zhy-cloud-disk.git && cd zhyCloudDisk

./deploy.sh init    # 首次从 .env.example 生成 .env，按需修改管理员密码、端口等
./deploy.sh up      # 构建镜像、后台启动，并自动轮询 /api/ping 做健康检查
```

`deploy.sh` 常用命令：

| 命令 | 说明 |
|------|------|
| `./deploy.sh init` | 生成 `.env`（已存在则跳过），所有变量见 [.env.example](https://gitee.com/pollybird/zhy-cloud-disk/blob/master/.env.example) |
| `./deploy.sh up` | 构建并启动（默认命令），完成后输出 Web 与客户端访问地址 |
| `./deploy.sh down` | 停止并移除容器（数据卷保留） |
| `./deploy.sh restart` | 重启服务并重新健康检查 |
| `./deploy.sh status` | 查看容器状态 |
| `./deploy.sh logs` | 跟踪全部服务日志（Ctrl+C 退出） |
| `./deploy.sh update` | 拉取最新代码后重新构建并滚动更新 |
| `./deploy.sh shell` | 进入后端容器（排障用） |

`.env` 关键变量（完整说明见 [配置参考](./08-Configuration.md)）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHY_WEB_PORT` | `8080` | Web 访问端口（映射到容器 80） |
| `ZHY_ADMIN_USERNAME` | `admin` | 超管用户名（仅首次静默安装生效） |
| `ZHY_ADMIN_PASSWORD` | `Admin12345` | 超管密码（**务必修改**，仅首次安装生效） |
| `ZHY_ADMIN_EMAIL` | `admin@zhy.local` | 超管邮箱 |
| `ZHY_DEPARTMENT_DRIVE` | `true`（compose 默认） | 是否开启部门共享网盘（仅首次安装生效） |

## 方式二：直接使用 Docker Hub 镜像

无需克隆仓库与构建：

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

首次启动自动完成安装（MySQL root 授权、建库建表、初始化超管账号），访问 `http://<服务器IP>:8080` 即可使用。可用标签：`latest`、`1.3.1`、`1.3.0`、`1.2.0`。

## 方式三：分步 Docker Compose 部署

```bash
# 1. 克隆仓库
git clone https://gitee.com/pollybird/zhy-cloud-disk.git && cd zhyCloudDisk

# 2. 配置环境变量（可选，不配置则使用默认值）
cp .env.example .env
# 编辑 .env：修改 ZHY_ADMIN_PASSWORD、ZHY_WEB_PORT 等

# 3. 构建并启动
docker compose up -d --build
```

容器内部请求链路：`宿主机:<ZHY_WEB_PORT>` → 容器内 nginx（80，`client_max_body_size 2g`）→ `/api/` 反代 `127.0.0.1:5000` gunicorn。

常用运维命令：

```bash
docker compose logs -f app     # 查看日志
docker compose restart         # 重启
docker compose down            # 停止（数据卷保留）
docker compose up -d --build   # 升级重建
```

## 数据卷与持久化

| Volume | 容器路径 | 用途 |
|--------|----------|------|
| `app-instance` | `/app/instance` | 安装配置（`config.installed.json`，含数据库连接、密钥、部门开关等） |
| `app-storage` | `/app/storage` | 用户上传文件实体（含 `blobs/` 内容寻址块与 `backups/` 本地备份包） |
| `app-mysql` | `/var/lib/mysql` | MySQL 数据 |

> 三个数据卷删除即数据丢失。备份策略建议见 [备份与恢复](./06-Backup-Restore.md#三数据卷备份建议)。

## 手动部署（无 Docker）

### 后端

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export ZHY_INSTANCE_DIR=./instance
export ZHY_STORAGE_DIR=./storage

python run.py                                  # 开发模式（0.0.0.0:5000）
gunicorn -w 4 -b 0.0.0.0:5000 wsgi:application # 生产模式
```

### 前端

```bash
cd frontend
npm install
npm run dev     # 开发
npm run build   # 生产构建，输出 dist/
```

生产环境用 nginx 托管 `dist/`，并将 `/api/` 反向代理到后端 5000 端口（参考容器内配置：`client_max_body_size 2g`，避免大文件上传被反代截断）。

### 安装向导

手动部署首次启动访问 `http://localhost:5000` 会进入 Web 安装向导（`/install`），依次完成：环境检测 → 数据库连接测试（SQLite / MySQL / PostgreSQL 直连 DSN）→ 存储目录校验 → 超管账号配置 → 执行安装。安装向导只可执行一次，完成后锁定（业务码 `2020`）。

> 数据库选择：SQLite 适合小规模；MySQL / MariaDB / PostgreSQL 需自行部署。**备份恢复功能 v1.3.0 仅支持 SQLite 与 MySQL**（PostgreSQL 会明确提示暂不支持），生产建议 MySQL。

## 静默安装与健康检查

满足以下条件时，容器/进程启动会自动完成安装（建库建表 + 创建超管），无需访问向导：

- 设置了 `ZHY_ADMIN_USERNAME` 与 `ZHY_ADMIN_PASSWORD`；
- Docker 模式（`ZHY_DOCKER=1`）自动使用内置 MySQL 与 Redis；
- 可通过 `ZHY_DEPARTMENT_DRIVE=true` 在静默安装时开启部门网盘。

健康检查接口：

```bash
curl http://<服务器IP>:8080/api/ping
# {"code":0,"msg":"ok","data":{"version":"1.3.1","installed":true}}
```

`deploy.sh up` 正是轮询该接口判断启动成功的。系统未安装时，除 `/api/ping` 与 `/api/setup/*` 外的业务接口统一返回 HTTP 503、业务码 `4001`。

## 桌面客户端连接服务端

- 客户端服务器地址**直接填 Web 访问地址**，例如 `http://<服务器IP>:8080`，与浏览器访问 Web 端相同，**无需带 `/api` 路径**；请求经 nginx `/api/` 反代到达后端，无需单独开放后端端口。
- 四步向导内含连通性测试，配置错误会当场提示。
- 详见 [桌面客户端](./04-Desktop-Client.md#首次运行向导)。

## HTTPS 建议

- 客户端 JWT 经系统密钥环（safeStorage/Keychain/DPAPI）加密保存，但传输仍是 HTTP 明文；**公网部署务必在前面增加 HTTPS 反向代理**（Caddy / nginx + certbot / 云负载均衡均可），客户端使用 `https://` 地址连接。
- 内网/可信环境可暂时使用 HTTP；如需限定跨域来源，设置 `ZHY_CORS_ORIGINS=https://disk.example.com`（默认 `*`）。
- 可选：容器后端端口默认仅绑定宿主机回环（排障时才建议 `ZHY_BACKEND_PORT` 映射 `0.0.0.0:5000`）。

## 升级流程

1. **升级前备份**：手动 / SQLite 部署备份 `backend/instance` 与存储目录；Docker 部署备份 `app-mysql` 与 `app-storage` 数据卷（详见 [备份与恢复](./06-Backup-Restore.md)）。
2. 拉取新代码：

```bash
git pull
./deploy.sh update        # Docker 部署：重新构建并滚动更新
# 或
docker compose up -d --build
```

3. 数据库**首次启动自动幂等迁移**（v1.1.0 补建部门表与相关列；v1.2.0 建 `file_blob`/`upload_session`/`upload_chunk`/`file_lock`；v1.3.0 加 `deleted_time`/`delete_operator_id` 列并新建 `trash_item`/`file_version`/`backup_record` 表），旧数据不受影响。
4. 升级后打开「系统管理 → 监控仪表盘」确认版本与指标正常；历史物理文件无需手动处理，每日 blob 收敛任务会逐步补算指纹并去重。

> 注意：Docker v1.2.0 起为全新单容器镜像（内置 MySQL），与 v1.1.0 多容器（SQLite + 独立 Redis）数据卷结构不同，不自动迁移旧容器数据，建议作为全新部署使用。

## 相关页面

- [配置参考（环境变量 / 设置键全表）](./08-Configuration.md)
- [备份与恢复](./06-Backup-Restore.md)
- [常见问题](./10-FAQ.md)
