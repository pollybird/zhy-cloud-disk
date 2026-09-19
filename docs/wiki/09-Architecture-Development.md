# 架构与开发

本页面向开发者与运维：技术栈与目录结构、物理存储与 blob 引用计数、关键数据流（上传/下载/同步/备份）、定时任务、三端本地开发与调试、测试套件运行方式、客户端打包发布与版本发布流程。

## 本页内容

- [技术栈](#技术栈)
- [目录结构](#目录结构)
- [物理存储与 blob 引用计数](#物理存储与-blob-引用计数)
- [关键数据流](#关键数据流)
- [定时任务](#定时任务)
- [本地开发与调试](#本地开发与调试)
- [测试套件](#测试套件)
- [客户端打包发布](#客户端打包发布)
- [版本发布流程](#版本发布流程)

---

## 技术栈

| 端 | 技术 |
|----|------|
| 后端 | Flask 3.0 + SQLAlchemy + Flask-JWT-Extended + Flask-CORS + APScheduler + Redis（可选，无则内存缓存）+ bcrypt + psutil + paramiko（SFTP 备份）+ cryptography（Fernet）+ PyMySQL / psycopg2-binary |
| 前端 | Vue 3 + Element Plus + Vite + Pinia + vue-router |
| 桌面客户端 | Electron 33 + electron-vite + Vue 3 + better-sqlite3（本地镜像库）+ chokidar（文件监听）+ axios + electron-store + auto-launch |
| 数据库 | SQLite（开发/手动部署）/ MySQL（Docker 镜像内置 MariaDB 11）/ 支持外部 MySQL / PostgreSQL |
| 部署 | Docker all-in-one 单容器：内置 MySQL + Redis + nginx + gunicorn（supervisor 托管） |

后端关键依赖版本见 [backend/requirements.txt](https://gitee.com/pollybird/zhy-cloud-disk/blob/master/backend/requirements.txt)（含 v1.3.1 显式声明的 `cryptography==50.0.1`）。

## 目录结构

```text
zhyCloudDisk/
├── Dockerfile             # all-in-one 镜像（内置 MySQL + Redis + nginx + gunicorn）
├── docker-compose.yml     # 单服务；数据卷 app-instance / app-storage / app-mysql
├── deploy.sh              # 一键部署脚本（init/up/down/restart/status/logs/update/shell）
├── .env.example           # 环境变量示例
├── backend/
│   ├── app/
│   │   ├── api/           # 蓝图接口（auth, file, department, permission, share, plugin, setup, user, admin, system, log）
│   │   ├── models/        # 数据模型（user, file_node, file_blob, file_lock, file_permission, department,
│   │   │                  #   share, trash_item, file_version, upload_session, backup_record,
│   │   │                  #   download_log, operation_log, plugin, system_setting）
│   │   ├── services/      # 业务逻辑（auth, file, department, permission, share, setup, cache,
│   │   │                  #   trash, version, metrics, backup, setting, blob, storage, file_lock, log, user）
│   │   ├── plugins/       # 插件框架（base, manager, builtin/image|video|document_preview）
│   │   ├── tasks/         # 定时任务（share/upload/lock/trash 清理、blob 收敛、指标采样、备份调度）
│   │   └── utils/         # 工具（response, errors, security, validators, decorators, crypto, migrations）
│   ├── tests/             # pytest 测试套件（206 项）
│   ├── wsgi.py            # gunicorn 生产入口（含静默安装钩子）
│   ├── run.py             # 开发入口 + 命令行安装向导（python run.py setup）
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── views/         # 页面（Files, Setup, Login, Register, Profile, DepartmentFiles,
│   │   │                  #   Departments, DepartmentMembers, PermissionManage, OperationLog,
│   │   │                  #   admin/{Users, Plugins, Dashboard, Backup, Settings}）
│   │   ├── components/    # 组件（PluginPreview, FileUploadDialog, TrashDrawer, VersionDialog, ...）
│   │   ├── stores/        # Pinia 状态管理
│   │   └── router/        # 路由与守卫（安装态/登录态/角色/部门功能拦截）
│   └── dist/              # 前端构建产物（构建镜像前需 npm run build）
├── client/                # Electron 桌面同步客户端
│   ├── src/
│   │   ├── main/          # 主进程：窗口、托盘、开机自启、IPC（同步历史/部门）
│   │   ├── preload/       # contextBridge 安全桥
│   │   ├── renderer/      # Vue3 界面：SetupWizard / SyncView / DepartmentView / SettingsView + TrashDialog/VersionDialog
│   │   └── lib/
│   │       ├── api/       # axios 封装（token 注入 / 401 刷新 / 文件与回收站版本接口）
│   │       ├── dept/      # 部门网盘：临时文件管理（排他锁 / 保存回传 / 关闭探测）、传输与上传树
│   │       ├── mirror/    # better-sqlite3 镜像库（远端树快照 / 本地指纹 / 同步日志）
│   │       ├── store/     # 设置持久化 + 加密 token（keystore）
│   │       └── sync/      # 同步引擎：watcher / poller / queue / reconciler / hasher / chunk-uploader / range-downloader
│   ├── tests/             # vitest 单元测试（131 用例）
│   └── resources/         # 应用图标
└── plugins/               # 外部插件目录（开发见 PLUGIN_DEVELOPMENT.md）
```

## 物理存储与 blob 引用计数

`ZHY_STORAGE_DIR`（Docker：`/app/storage`）下的布局：

```text
storage/
├── blobs/                 # 内容寻址块：blobs/<hash前2位>/<hash全名>，跨用户共享
├── backups/               # 本地备份包（zhy-backup-*.zip）与恢复临时文件
└── uploads/...            # 分片上传暂存（tmp/<session>），完成后并入 blob 或普通目录
```

- **file_blob 表**：全局指纹库，字段含 MD5、大小、物理路径、`ref_count`。
- **引用计数规则**：
  - 上传命中/落盘时 `ref_count` +1（数据库唯一约束 + 原子更新保证并发只落一份）；
  - 删除（回收站彻底删除）、版本清理、文件硬删除时 -1；**引用归零才物理删除**（带 `ref_count > 0` 守卫）；
  - 历史版本每份多一个引用，因此多版本不重复占盘；
  - 各用户/部门的**逻辑配额**独立于物理去重照常扣减。
- **每日 blob 收敛任务**：为 1.0/1.1 旧文件补算 MD5（每轮限量）→ 非 blob 路径物理文件按 hash+size 归并（同内容多份只留一份，FileNode 改指 blob）→ 对账 `ref_count` → 清理无主 blob/孤儿文件。全程幂等、可中断，物理删除在 DB 提交之后。

## 关键数据流

### 上传（个人/部门统一三级通道）

```text
客户端计算 MD5 → POST /file/instant（秒传预检）
  ├─ 命中：建引用，零带宽完成
  └─ 未命中：>20MB → /file/chunk/init|upload|complete（5MB 分片、并发 3、断点续传、双 MD5）
              ≤20MB → /file/upload 整文件
  → 配额原子扣减（超额 UPDATE 影响 0 行 → 3106）
  → blob 落盘 + ref_count+1 / FileNode 建档 → 审计与流量统计
```

### 下载

```text
GET /file/download（或 /share/download、/plugin/file/stream）
  → 鉴权（JWT / 分享令牌 / 插件钩子）→ 打开物理文件 → send_file（conditional=True）
  → 支持 Range 206；无 Range 记录 download_log；客户端 .zhy.part 续传 + 完成后 MD5 校验
```

### 桌面端同步

```text
本地变更 → chokidar（重命名/移动智能配对）→ 任务队列（串行/去重/退避重试）→ 上传通道
云端变更 → poller（默认 60s）→ 远端 diff（镜像库快照对比）→ 协调器 → 下载（Range 续传）
冲突 → 冲突策略（keep-both 生成服务器冲突副本 / last-write-wins）
```

### 备份与恢复

```text
备份：手动（后台线程）/ 定时（每小时:17 检查）→ DB 快照（sqlite 文件 / mariadb-dump|mysqldump）
      → 打包 config.installed.json + manifest.json(SHA-256) → 本地 storage/backups/ 或 SFTP/FTP 上传 → 按保留份数淘汰
恢复：confirm 校验 → 安全解压 + SHA-256 校验 → pre-restore 快照（当前库）→ 导入（MySQL 先释放连接池防 MDL 等锁）
      → 清理设置/插件/JWT 吊销缓存 → 回写安装配置 → 2s 后进程退出由守护拉起
```

## 定时任务

完整清单与周期见 [配置参考 · 定时任务清单](./08-Configuration.md#定时任务清单)（15s 指标采样、5min 锁清理、10min 分享/分片清理、1h 回收站清理、24h blob 收敛、每小时 :17 备份调度）。多进程部署下任务幂等（数据库条件更新兜底），多实例同时运行不会出错。

## 本地开发与调试

### 后端

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ZHY_INSTANCE_DIR=./instance ZHY_STORAGE_DIR=./storage ZHY_ENV=development
python run.py            # 开发服务器（0.0.0.0:5000，debug）
python run.py setup      # 命令行交互式安装（替代 Web 向导）
```

- 未安装态只有 `/api/ping` 与 `/api/setup/*` 可用，其余返回 503/`4001`。
- 无 Redis 时缓存自动降级为进程内存缓存；切换数据库改 `ZHY_DATABASE_URL`。

### 前端

```bash
cd frontend
npm install
npm run dev      # Vite 开发服务器（代理 /api 到本地后端）
npm run build    # 生产构建 → dist/
```

### 客户端

```bash
cd client
npm install                 # .npmrc 已指向 npmmirror（Electron / better-sqlite3 二进制）
npm run dev                 # electron-vite 开发模式
npx electron-vite build && ./node_modules/.bin/electron .   # 构建后直接运行
```

> Linux 无 root 开发环境：`./node_modules/.bin/electron --no-sandbox --disable-gpu-sandbox .`。better-sqlite3 ABI 不匹配时执行 `npx electron-rebuild -f -w better-sqlite3`。

## 测试套件

| 端 | 命令 | 规模 |
|----|------|------|
| 后端 | `cd backend && .venv/bin/python -m pytest tests/ -v` | **206** 项 |
| Web 前端 | `cd frontend && npx vitest run` | **25** 项（分片编排器、部门树、文件分类等） |
| 桌面客户端 | `cd client && npm test`（监听：`npm run test:watch`） | **131** 项 |

客户端测试覆盖：任务队列（串行/去重/退避重试）、远端 diff 协调器、路径映射、MD5 计算、HTTP 拦截器（401 自动刷新）、设置持久化、token 加密存储、分片上传 / Range 断点下载、部门文件排他锁生命周期等核心逻辑。

## 客户端打包发布

```bash
cd client
npm run package:linux   # Linux AppImage
npm run package:win     # Windows 免安装便携版（portable exe）
npm run package:mac     # macOS zip（x64 + arm64；macOS 本机构建可改 dmg）
```

- 底层为 `electron-vite build && electron-builder --linux AppImage / --win portable / --mac zip`。
- 产物输出到 `client/dist/`。
- 正式安装包（deb/AppImage）自动配置 chrome-sandbox 沙箱，无需 `--no-sandbox`。

## 版本发布流程

以 v1.3.x 为例（与仓库 CHANGELOG 记录一致）：

1. **功能合入与自测**：三端测试全绿（后端 pytest / 前端 vitest / 客户端 vitest），必要时做真实 Docker E2E（如备份恢复全流程）。
2. **版本号**：遵循[语义化版本](https://semver.org/lang/zh-CN/)；更新 `backend/app/config.py` 的 `ZHY_VERSION`。
3. **CHANGELOG.md**：按「主题 → 新功能 / 修复与加固 / 升级说明 / 质量保障」结构记录。
4. **Docker 镜像**：构建并推送 Docker Hub `pollybird/zhy-cloud-disk` 的 `latest` 与版本号标签（如 `1.3.1`）。
5. **仓库发布**：同步 Gitee（主）、GitHub、GitCode 三个仓库并打 tag。

## 相关页面

- [API 参考](./07-API-Reference.md)
- [配置参考](./08-Configuration.md)
- [备份与恢复（数据流细节）](./06-Backup-Restore.md)
