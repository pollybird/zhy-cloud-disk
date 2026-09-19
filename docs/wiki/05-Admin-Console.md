# 管理后台

本页面向超级管理员与部门管理员，介绍管理后台各页面：用户管理、系统设置（全部设置项表）、监控仪表盘（各指标口径说明）与插件管理。

## 本页内容

- [页面导航与权限](#页面导航与权限)
- [用户管理](#用户管理)
- [系统设置](#系统设置)
- [监控仪表盘](#监控仪表盘)
- [插件管理](#插件管理)
- [备份与日志入口](#备份与日志入口)

---

## 页面导航与权限

Web 端左侧菜单结构（路由来自 `frontend/src/router`）：

| 菜单 | 路由 | 可见/可进条件 |
|------|------|---------------|
| 文件 | `/files` | 所有登录用户 |
| 我的分享 | `/shares` | 所有登录用户 |
| 个人中心 | `/profile` | 所有登录用户（改密码） |
| 部门网盘 | `/department-files` | 功能开启且为部门成员 |
| 部门管理 | `/departments` | 功能开启且（超管或部门管理员） |
| 部门成员 | `/department-members` | 同上 |
| 权限管理 | `/admin/permissions` | 同上 |
| 操作日志 | `/admin/logs` | 同上 |
| 用户管理 | `/admin/users` | 仅超管 |
| 插件管理 | `/admin/plugins` | 仅超管 |
| 监控仪表盘 | `/admin/dashboard` | 仅超管 |
| 备份恢复 | `/admin/backup` | 仅超管 |
| 系统设置 | `/admin/settings` | 仅超管 |

公开页面：`/install`（安装向导）、`/login`、`/register`、`/share/:code`（分享访问）。

## 用户管理

「用户管理」页（仅超管）：

| 操作 | 接口 | 说明 |
|------|------|------|
| 用户列表 | `GET /api/admin/users?q=&page=&size=` | 关键词搜索（用户名/邮箱），分页默认 20、最大 100 |
| 新建用户 | `POST /api/admin/users` | 与自助注册独立，可指定角色（`admin`/`user`）与配额；校验用户名 3–32 位、密码 8–64 位且含字母数字 |
| 编辑用户 | `PUT /api/admin/users/<id>` | 角色、状态、配额；不能修改自己的角色/启用状态（`1210`），系统至少保留一个启用状态的管理员（`1211`）；管理员不能代改他人密码（`1213`） |
| 调整配额 | `PUT /api/admin/users/<id>/quota` | 正整数字节；不能低于已用空间（`1205`） |
| 启用/禁用 | `PUT /api/admin/users/<id>/status` | `active` / `disabled`；禁用后该用户立即无法访问 |

自助注册默认关闭；开放后注册页可见（`GET /api/auth/register-status`），注册用户角色为 `user`、配额取默认值。

## 系统设置

「系统设置」页（`/admin/settings`）对应接口 `GET /api/admin/settings` / `PUT /api/admin/settings`。保存为**两阶段校验**：全部字段校验通过后才统一写入，避免远端配置半写入。

### 全部设置项

| 设置项 | 键 | 类型 | 默认值 | 取值范围/校验 |
|--------|----|------|--------|----------------|
| 开放游客注册 | `allow_register` | bool | `false` | 布尔（`1220`） |
| 回收站开关 | `trash_enabled` | bool | `true` | 布尔 |
| 回收站保留天数 | `trash_retention_days` | int | `30` | 1–365（`1222`） |
| 历史版本开关 | `version_enabled` | bool | `true` | 布尔 |
| 每文件最大版本数 | `version_max_count` | int | `10` | 1–100 |
| 版本保留天数 | `version_retention_days` | int | `30` | 1–365 |
| 定时备份开关 | `backup_enabled` | bool | `false` | 布尔 |
| 每日备份小时 | `backup_hour` | int | `3` | 0–23 |
| 备份保留份数 | `backup_keep_count` | int | `7` | 1–100 |
| 备份目标 | `backup_target` | string | `local` | `local` / `remote`（`1222`） |
| 远端协议 | `backup_protocol` | string | `sftp` | `sftp` / `ftp` |
| 远端主机 | `backup_host` | string | 空 | 目标为 remote 时必填（`1223`） |
| 远端端口 | `backup_port` | int | SFTP 22 / FTP 21 | 1–65535 |
| 远端用户名 | `backup_username` | string | 空 | — |
| 远端密码 | `backup_password` | string | 空 | Fernet 加密入库；接口永不回传明文；留空提交=不修改 |
| 远端目录 | `backup_remote_dir` | string | `/zhy-backups` | 不存在时自动逐级创建 |

类型错误统一返回 `1221`（必须为整数/布尔/字符串），范围/枚举错误返回 `1222`。

### 设置接口调用示例

读取当前全量设置：

```bash
curl -H "Authorization: Bearer <access_token>" http://<host>/api/admin/settings
```

修改若干设置项（只需传要改的字段，全部校验通过才写入）：

```bash
curl -X PUT -H "Authorization: Bearer <access_token>" -H "Content-Type: application/json" \
  -d '{
    "trash_retention_days": 90,
    "version_max_count": 20,
    "backup_enabled": true,
    "backup_hour": 2,
    "backup_keep_count": 14,
    "backup_target": "remote",
    "backup_protocol": "sftp",
    "backup_host": "sftp.example.com",
    "backup_port": 22,
    "backup_username": "ops",
    "backup_password": "<新密码>",
    "backup_remote_dir": "/zhy-backups"
  }' http://<host>/api/admin/settings
```

注意：`backup_password` 仅在需要更换时提交，留空或不传表示保持原密码；目标为 `remote` 时必须能解析出主机（`1223`）。

> 另有安装期持久化的 `department_drive_enabled`（部门网盘开关），启动时读取；当前版本的系统设置接口不提供修改入口，见 [常见问题](./10-FAQ.md)。

设置读取有 **60 秒缓存**（Redis/内存），变更后多 worker 最多延迟 60 秒生效。

## 监控仪表盘

「监控仪表盘」页（`/admin/dashboard`）对应 `GET /api/admin/metrics`，页面支持 **30 秒自动刷新**。返回结构：

```json
{
  "cpu": {}, "memory": {}, "disk": {}, "online_users": 0,
  "traffic": {}, "storage": {}, "generated_at": "..."
}
```

### 指标口径

| 指标 | 口径 |
|------|------|
| CPU | 基于 psutil 的进程 CPU 使用率；**容器内自动读取 cgroup v1/v2 限额**，正确显示配额核数；采样任务每 **15 秒**刷新一次（缓存读取） |
| 内存 | 容器内读取 cgroup v1/v2 内存上限与用量；无 cgroup 时按宿主机口径 |
| 磁盘 | 统计**存储目录所在文件系统**（`STORAGE_DIR`）的总量/已用/可用/百分比；页面 ≥90% 红色、≥70% 黄色预警 |
| 在线人数 | **5 分钟窗口**内活跃用户数（按 `last_active_time` 去重统计）；活跃时间每用户 60 秒节流落库 |
| 今日上/下行流量 | 进程内聚合、周期批量落库（`system_setting` 表按日 key），覆盖上传下载与分享/插件流 |
| 近 7 天流量 | 双柱图（纯 SVG，无新增前端依赖），按日聚合，超期 key 自动清理 |
| 存储统计 | 已用空间/总配额进度条；个人盘/部门盘占用、文件数、文件夹数、用户数、部门数（均只统计 `normal` 状态） |

## 插件管理

「插件管理」页（`/admin/plugins`）对应接口 `GET /api/plugin/list`、`POST /api/plugin/register`、`PUT /api/plugin/<name>/enabled`。

- **内置插件**：`image_preview`（图片预览）、`video_preview`（视频预览，支持拖动 seek）、`document_preview`（文档预览）。
- **插件目录**：内置 `backend/app/plugins/builtin/` + 仓库根 `plugins/` 外部目录；外部插件开发见 [PLUGIN_DEVELOPMENT.md](https://gitee.com/pollybird/zhy-cloud-disk/blob/master/PLUGIN_DEVELOPMENT.md)。
- **注册/启停**：「注册」重扫描插件目录并同步注册表（可顺带启用指定插件）；启用/禁用立即生效，禁用的插件文件流/保存请求返回 `5102`。
- **预览挂载**：Web 端文件预览按后缀匹配已启用插件（`GET /api/plugin/available?suffix=`）。

## 备份与日志入口

- **备份恢复**：独立页面，功能与流程见 [备份与恢复](./06-Backup-Restore.md)。
- **操作日志**：全局日志（超管）在 `/admin/logs` 或部门日志入口查看，见 [部门网盘使用 · 审计日志](./03-Department-Drive.md#审计日志)。

## 管理端常见问题对照

| 现象 | 原因与处理 |
|------|------------|
| 设置保存报「backup_port 必须是 1~65535 的整数」等 | 两阶段校验拦截（`1221`/`1222`），修正后整体重新提交；不会出现半写入 |
| 改了系统设置但部分接口行为延迟变化 | 设置读取有 60 秒缓存（Redis/内存），最多延迟 60 秒生效 |
| 用户改了角色/状态却「不能修改自己」 | 系统禁止自我修改角色与启用状态（`1210`），且始终保留至少一个启用管理员（`1211`） |
| 仪表盘 CPU 核数与宿主机不一致 | 容器内按 cgroup v1/v2 配额显示限额核数，属正确口径 |
| 仪表盘在线人数偏少 | 按 5 分钟窗口活跃统计；活跃落库每用户 60 秒节流，新请求不即时计入 |
| 新建用户没有生效新配额 | `ZHY_DEFAULT_QUOTA` 只影响之后新建的用户，存量用户在「用户管理」单独调整 |
| 监控页流量与文件大小总和不符 | 流量按传输字节统计（含分片重试、重复下载），非文件逻辑大小 |

## 相关页面

- [备份与恢复](./06-Backup-Restore.md)
- [配置参考 · 系统设置键全表](./08-Configuration.md#系统设置键)
- [API 参考 · 管理员/用户蓝图](./07-API-Reference.md)
