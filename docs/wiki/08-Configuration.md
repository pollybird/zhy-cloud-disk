# 配置参考

本页汇总 zhyCloudDisk 全部配置项：环境变量全表（标注仅首装生效项）、系统设置键全表（含默认值与校验规则）、桌面客户端设置、以及后台定时任务清单。内容以代码（`backend/app/config.py`、`setting_service.py`、`tasks/scheduler.py`、客户端 `lib/store/settings.js`）为准。

## 本页内容

- [环境变量全表](#环境变量全表)
- [系统设置键](#系统设置键)
- [客户端设置](#客户端设置)
- [定时任务清单](#定时任务清单)
- [配置加载优先级](#配置加载优先级)

---

## 环境变量全表

配置加载链：**环境变量 > instance/config.installed.json（安装向导落盘）> 代码默认值**。

### 部署与运行

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHY_DOCKER` | `0` | Docker 模式（设为 `1` 时自动使用内置 MySQL + Redis，跳过数据库配置，安装向导跳过数据库步骤） |
| `ZHY_ENV` | `production` | `development` 时 run.py 开启 Flask debug |
| `ZHY_INSTANCE_DIR` | `backend/instance` | 实例目录（安装配置 `config.installed.json`、SQLite 数据文件、pre-restore 快照） |
| `ZHY_STORAGE_DIR` | `backend/storage` | 文件存储根目录（可被安装配置覆盖；Docker 容器内为 `/app/storage`） |
| `ZHY_HOST` / `ZHY_PORT` | `0.0.0.0` / `5000` | 仅 `python run.py` 开发服务器监听地址/端口 |
| `ZHY_WEB_PORT` | `8080` | 仅 docker compose / deploy.sh：Web 端口映射（容器 80） |
| `ZHY_BACKEND_PORT` | 不映射 | 可选后端端口映射（默认后端仅绑定容器内 `127.0.0.1:5000`） |

### 安装（均仅首次安装生效）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHY_ADMIN_USERNAME` | — | 超管用户名（与 `ZHY_ADMIN_PASSWORD` 同时设置时触发静默安装） |
| `ZHY_ADMIN_PASSWORD` | — | 超管密码 |
| `ZHY_ADMIN_EMAIL` | — | 超管邮箱 |
| `ZHY_DATABASE_URL` | SQLite（`instance/preinstall.db`） | SQLAlchemy 连接串；Docker 模式自动使用内置 MySQL（`mysql+pymysql://root@127.0.0.1:3306/zhycloud`） |
| `ZHY_REDIS_URL` | 空（内存缓存） | Redis 连接串；Docker 模式自动使用 `redis://127.0.0.1:6379/0` |
| `ZHY_DEPARTMENT_DRIVE` | `false`（代码默认） | 静默安装时是否开启部门共享网盘（`true`/`false`）。**注意**：docker compose/.env.example 模板默认 `true`；仅首次安装生效，启动时从设置读取 |
| `ZHY_ALLOW_REGISTER` | `false` | 是否开放游客注册（安装后数据库设置优先） |

### 密钥与业务参数（运行期读取）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHY_SECRET_KEY` | 开发占位串 | Flask SECRET_KEY；未显式设置时安装向导生成随机值写入安装配置 |
| `ZHY_JWT_SECRET_KEY` | 开发占位串 | JWT 签名密钥；同上由安装向导生成 |
| `ZHY_JWT_ACCESS_HOURS` | `2` | Access Token 有效期（小时） |
| `ZHY_JWT_REFRESH_DAYS` | `30` | Refresh Token 有效期（天） |
| `ZHY_DEFAULT_QUOTA` | `5368709120`（5GiB） | 默认用户配额（字节）；仅影响新建用户/安装时超管 |
| `ZHY_MAX_UPLOAD_SIZE` | `2147483648`（2GiB） | 单文件上传上限（字节），同时作为 Flask `MAX_CONTENT_LENGTH` |
| `ZHY_CORS_ORIGINS` | `*` | CORS 允许源；多个用英文逗号分隔（如 `https://a.com,https://b.com`） |

> `.env.example`（Docker 部署模板）包含：`ZHY_WEB_PORT`、`ZHY_ADMIN_USERNAME`、`ZHY_ADMIN_PASSWORD`、`ZHY_ADMIN_EMAIL`（默认 `admin@zhy.local`）、`ZHY_DEPARTMENT_DRIVE`、`ZHY_JWT_ACCESS_HOURS`、`ZHY_JWT_REFRESH_DAYS`、`ZHY_DEFAULT_QUOTA`、`ZHY_CORS_ORIGINS`。

## 系统设置键

持久化于 `system_setting` 表，读取有 60 秒缓存（Redis/内存），变更后多 worker 最多延迟 60 秒生效。通过「系统管理 → 系统设置」或 `PUT /api/admin/settings` 修改。

| 键 | 类型 | 默认值 | 校验/说明 |
|----|------|--------|-----------|
| `allow_register` | bool | `false` | 开放游客注册；数据库显式设置优先于安装配置/环境变量 |
| `trash_enabled` | bool | `true` | 回收站开关；关闭后新删除走硬删除，**不清毁存量** |
| `trash_retention_days` | int | `30` | 回收站保留天数，1–365 |
| `version_enabled` | bool | `true` | 历史版本开关；关闭后不产生新版本，存量仍可查看/下载/恢复 |
| `version_max_count` | int | `10` | 每文件最大版本数，1–100 |
| `version_retention_days` | int | `30` | 版本保留天数，1–365 |
| `backup_enabled` | bool | `false` | 每日定时备份开关 |
| `backup_hour` | int | `3` | 每日备份执行小时，0–23（调度器每小时 :17 检查，改值无需重启） |
| `backup_keep_count` | int | `7` | 备份保留份数，1–100 |
| `backup_target` | string | `local` | `local` / `remote` |
| `backup_protocol` | string | `sftp` | `sftp` / `ftp` |
| `backup_host` | string | 空 | 远端主机；`backup_target=remote` 时必填 |
| `backup_port` | int | SFTP 22 / FTP 21 | 1–65535 |
| `backup_username` | string | 空 | 远端用户名 |
| `backup_password_enc` | string | 空 | Fernet 加密后的密码（接口提交字段为 `backup_password` 明文，留空=不修改） |
| `backup_remote_dir` | string | `/zhy-backups` | 远端目录，不存在自动逐级创建 |
| `department_drive_enabled` | bool | `false` | 部门网盘开关；**安装时写入**（向导/静默安装），服务启动时读取一次；系统设置接口当前不提供修改入口 |
| `traffic_up:<YYYY-MM-DD>` / `traffic_down:<日期>` | int | — | 内部键：按日流量统计，超期自动清理，勿手工修改 |

校验错误码：类型错误 `1221`、取值越界/枚举非法 `1222`、远端必填缺失 `1223`、`allow_register` 非布尔 `1220`。保存为两阶段校验（全部通过才写入）。

## 客户端设置

桌面客户端设置持久化在 electron-store（`settings.json`），见 [桌面客户端](./04-Desktop-Client.md#客户端设置项)：

| 键 | 默认值 | 说明 |
|----|--------|------|
| `serverUrl` | 空 | 服务器地址（Web 地址，无需 `/api`；向导后只读） |
| `username` | 空 | 登录账号（向导后只读） |
| `syncPath` | 空 | 本地同步文件夹绝对路径 |
| `autoStart` | `false` | 开机自启 |
| `pollInterval` | `60` | 云端变更轮询间隔（秒），10–600 |
| `conflictStrategy` | `keep-both` | 冲突策略：`keep-both` 保留两者 / `last-write-wins` 最后修改者胜出 |
| `configured` | `false` | 是否完成首次配置（重置后回到向导） |

JWT 另存于系统密钥环（safeStorage/Keychain/DPAPI 加密），不在 settings.json 中。

## 定时任务清单

由 APScheduler 注册（`backend/app/tasks/scheduler.py`），全部幂等，多进程同时运行安全：

| 任务 ID | 周期 | 作用 |
|---------|------|------|
| `metrics-sampler` | 每 **15 秒** | 采样 CPU 使用率（含 cgroup v1/v2 配额识别），写入缓存供仪表盘读取 |
| `lock-cleanup` | 每 **5 分钟** | 物理删除过期排他编辑锁（TTL 2 分钟）行 |
| `share-cleanup` | 每 **10 分钟** | 把到期分享置为 `expired` |
| `upload-cleanup` | 每 **10 分钟** | 清理过期（24h）分片上传会话与分片记录、删除对应 tmp 目录、清理无 DB 记录的孤儿暂存目录 |
| `trash-cleanup` | 每 **1 小时** | 彻底删除超过保留期的回收站条目并释放 blob 引用 |
| `blob-adopt` | 每 **24 小时** | 存量收敛：为旧文件补算 MD5（每轮限量）、把非 blob 物理文件按 hash+size 归并进 blob 存储、对账修正引用计数、清理孤儿 blob |
| `backup-schedule` | 每小时 **:17**（cron） | 检查 `backup_enabled` 与 `backup_hour`，命中则执行备份并按保留份数淘汰（改配置无需重启） |

> 版本超量/到期清理不在独立定时任务中：每次覆盖上传归档新版本时同步执行 `prune_versions`（按每文件版本数与保留天数清理）。

## 常见场景配置示例

### 场景 1：最小化 Docker 部署（仅改密码与端口）

`.env` 只需关注：

```bash
ZHY_WEB_PORT=8080
ZHY_ADMIN_USERNAME=admin
ZHY_ADMIN_PASSWORD=<强密码>       # 仅首次安装生效
ZHY_ADMIN_EMAIL=admin@example.com
ZHY_DEPARTMENT_DRIVE=false       # 不需要部门网盘时显式关闭
```

### 场景 2：手动部署 + 外部 MySQL

```bash
export ZHY_INSTANCE_DIR=/data/zhy/instance
export ZHY_STORAGE_DIR=/data/zhy/storage
export ZHY_DATABASE_URL=mysql+pymysql://zhy:<密码>@127.0.0.1:3306/zhycloud?charset=utf8mb4
export ZHY_REDIS_URL=redis://127.0.0.1:6379/0    # 可选，无则内存缓存
gunicorn -w 4 -b 0.0.0.0:5000 wsgi:application
```

> 需在安装向导/静默安装前建好库与账号；`config.installed.json` 生成后数据库连接以安装配置为准（环境变量优先级更高，但两者应保持一致）。

### 场景 3：收紧安全项

```bash
export ZHY_CORS_ORIGINS=https://disk.example.com   # 限定跨域源
export ZHY_ALLOW_REGISTER=false                    # 关闭自助注册（也可在后台切）
export ZHY_MAX_UPLOAD_SIZE=1073741824              # 上限降到 1GiB
export ZHY_JWT_ACCESS_HOURS=1                      # 缩短 access token 有效期
```

### 场景 4：备份策略（管理后台热更，无需重启）

- 开启 `backup_enabled`、`backup_hour=2`（凌晨 2 点）、`backup_keep_count=14`；
- `backup_target=remote`、`backup_protocol=sftp`、`backup_port=22`、`backup_remote_dir=/ops/zhy`；
- 先点「测试连接」再保存；远端失败时本地包仍保留。

## 配置加载优先级

```text
运行期配置：环境变量 ZHY_* > instance/config.installed.json > 代码默认值
系统设置：  system_setting 表（DB） > 安装配置/环境变量回退 > 代码默认值
            （allow_register 等少数键有回退链；备份/回收站/版本键直接用默认值）
注册开关：  DB 设置 > ALLOW_REGISTER 配置（安装配置/环境变量） > false
```

- `config.installed.json` 由安装向导/静默安装一次性写入：版本、安装时间、数据库连接、存储目录、随机生成的 `secret_key`/`jwt_secret_key`、默认配额、上传上限、注册开关、Redis、部门开关等；**密码不落盘**。
- 修改部署级配置（端口、数据库、密钥）通常需要重新安装或直接改环境变量 + 重启；业务级策略（回收站、版本、备份、注册）全部在管理后台热更。

## 相关页面

- [安装部署（.env 与静默安装）](./01-Installation.md)
- [管理后台 · 系统设置](./05-Admin-Console.md#系统设置)
- [API 参考 · 管理员/用户蓝图](./07-API-Reference.md#认证与用户-auth--user)
