# 钟毓私有云盘（zhyCloudDisk）

基于 Flask + Vue3 的轻量私有云盘系统，支持文件管理、分享、插件扩展。

> Copyright (c) 2026 泰州姜堰钟毓信息技术有限公司. 本项目基于 [Apache License 2.0](./LICENSE) 开源。

## 仓库地址

- Gitee：<https://gitee.com/pollybird/zhy-cloud-disk>
- GitHub：<https://github.com/pollybird/zhy-cloud-disk>

## 技术栈

- **后端**：Flask 3.0 + SQLAlchemy + Flask-JWT-Extended + APScheduler + Redis（可选）
- **前端**：Vue 3 + Element Plus + Vite + Pinia
- **数据库**：SQLite（开发）/ MySQL / PostgreSQL（生产）
- **部署**：Docker Compose（gunicorn + nginx）

## Docker 一键部署

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

## 开发测试

```bash
# 后端测试
cd backend && .venv/bin/python -m pytest tests/ -v

# 前端构建
cd frontend && npm run build
```

## 架构概览

```
zhyCloudDisk/
├── backend/
│   ├── app/
│   │   ├── api/           # 蓝图接口（auth, file, share, plugin, setup, user）
│   │   ├── models/        # 数据模型（user, file_node, share, download_log, ...）
│   │   ├── services/      # 业务逻辑（auth, file, share, setup, cache, ...）
│   │   ├── plugins/       # 插件框架（base, manager, builtin/）
│   │   ├── tasks/         # 定时任务（过期分享清理）
│   │   └── utils/         # 工具（response, errors, security, validators, decorators）
│   ├── tests/             # pytest 测试套件（73 用例）
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
├── plugins/               # 外部插件目录
├── docker-compose.yml
└── README.md
```
