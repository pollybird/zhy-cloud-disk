# API 参考

本页列出 zhyCloudDisk 后端全部 HTTP 接口：调用约定（Base URL、JWT Bearer、`{code,msg,data}` 包装、分页参数）、按蓝图分节的端点表，以及业务错误码总表。所有端点均以后端代码（`backend/app/api/`）为准。

## 本页内容

- [调用约定](#调用约定)
- [健康检查与系统](#健康检查与系统)
- [认证与用户](#认证与用户-auth--user)
- [安装向导](#安装向导-setup)
- [文件管理](#文件管理-file)
- [分享](#分享-share)
- [部门管理](#部门管理-department)
- [权限管理](#权限管理-permission)
- [审计日志](#审计日志-log)
- [插件](#插件-plugin)
- [管理员（监控与备份）](#管理员-admin)
- [业务错误码总表](#业务错误码总表)

---

## 调用约定

| 项目 | 说明 |
|------|------|
| Base URL | `http(s)://<host>[:port]/api`（Docker 部署经 nginx 80 反代；桌面客户端填 Web 地址即可，无需 `/api`） |
| 认证 | `Authorization: Bearer <access_token>`；刷新令牌仅用于 `POST /api/auth/refresh` |
| 响应包装 | 统一 `{ "code": 0, "msg": "...", "data": ... }`；`code=0` 成功；HTTP 状态码 200 成功 / 4xx 5xx 错误 |
| 业务错误 | 失败时 `code` 为业务码（见[总表](#业务错误码总表)），`msg` 为中文提示；部分错误 `data` 携带附加信息（如锁冲突返回持有者） |
| Content-Type | JSON 接口 `application/json`；上传类接口 `multipart/form-data` |
| 分页参数 | 通用 `page`（≥1，默认 1）与 `size`（文件列表默认 50 最大 200；用户/日志默认 20 最大 100） |
| 时间格式 | ISO 8601（UTC） |

`GET /api/system/feature-flags`（需登录）返回当前功能开关：`department_drive` / `trash_enabled` / `version_enabled`。

## 健康检查与系统

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/ping` | 公开 | 健康检查，返回 `{version, installed}` |
| GET | `/api/system/feature-flags` | 登录 | 功能模块开关 |

未安装时除 `/api/ping`、`/api/setup/*` 外的所有 `/api` 请求返回 HTTP 503、业务码 `4001`。

## 认证与用户（auth / user）

| 方法 | 路径 | 权限 | 请求 | 返回 data 概要 |
|------|------|------|------|----------------|
| GET | `/api/auth/register-status` | 公开 | — | `{allow_register}` |
| POST | `/api/register` | 公开 | `{username, email, password}` | `{user}` |
| POST | `/api/login` | 公开 | `{username, password}` | `{access_token, refresh_token, user}` |
| POST | `/api/auth/refresh` | Refresh Token | — | `{access_token, refresh_token}`（账号被禁用返回 `4014`） |
| POST | `/api/logout` | 登录 | — | 吊销当前 access token 的 jti |
| GET | `/api/user/info` | 登录 | — | `{user}` |
| PUT | `/api/user/pwd` | 登录 | `{old_password, new_password}` | 修改本人密码 |
| GET | `/api/admin/users` | 超管 | `?q=&page=&size=` | 用户分页列表 |
| POST | `/api/admin/users` | 超管 | `{username, email, password, role?, total_storage?}` | `{user}` |
| PUT | `/api/admin/users/<id>` | 超管 | `{role?, status?, total_storage?}` | `{user}` |
| PUT | `/api/admin/users/<id>/quota` | 超管 | `{total_storage}` | `{user}` |
| PUT | `/api/admin/users/<id>/status` | 超管 | `{status}` | `{user}` |
| GET | `/api/admin/settings` | 超管 | — | 全部系统设置键值（见 [配置参考](./08-Configuration.md)） |
| PUT | `/api/admin/settings` | 超管 | 设置项任意子集（JSON） | 保存后的全量设置 |

## 安装向导（setup）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/setup/status` | 公开 | `{installed, version}` |
| GET | `/api/setup/environment` | 公开（仅未安装） | 环境检测（磁盘、存储目录等） |
| POST | `/api/setup/test-db` | 公开（仅未安装） | 测试数据库连接与写权限；`{database_uri}` 直连 DSN 或分字段 |
| POST | `/api/setup/install` | 公开（仅未安装，一次性） | 执行安装：写配置、建表、创建超管；payload 含 `admin_username/admin_email/admin_password`、数据库配置、`storage_dir`、`department_drive_enabled` 等 |

已安装后再调用会返回 HTTP 403、业务码 `2020`。

## 文件管理（file）

### 列表与基础操作

| 方法 | 路径 | 权限 | 请求 | 说明 |
|------|------|------|------|------|
| GET | `/api/file/list` | 登录 | `?parent_id=&department_id=&category=&keyword=&page=&size=` | 文件列表（部门列表项含 `locked`/`locked_by_me`/`lock_user_name`） |
| GET | `/api/file/folders` | 登录 | `?parent_id=&department_id=` | 子文件夹列表（移动对话框用） |
| GET | `/api/file/download` | 登录 | `?id=` | 文件下载，支持 Range 206；写下载日志 |
| POST | `/api/folder/create` | 登录 | `{parent_id?, department_id?, file_name}` | 创建文件夹 |
| PUT | `/api/file/rename` | 登录 | `{id, file_name}` | 重命名（被他人锁定返回 `3501`） |
| PUT | `/api/file/move` | 登录 | `{id, target_parent_id?}` | 移动 |
| DELETE | `/api/file/delete` | 登录 | `{id}`（或 query `id`） | 删除（回收站开启=软删除） |

### 上传（秒传 / 分片）

| 方法 | 路径 | 请求 | 说明 |
|------|------|------|------|
| POST | `/api/file/upload` | multipart：`files[]`、`parent_id?`、`file_hash?`、`mode?`、`overwrite_id?`、`department_id?` | 传统整文件上传（兼容）；返回 `{success:[], failed:[]}` |
| POST | `/api/file/check-duplicate` | `{parent_id?, file_name, file_hash?, department_id?}` | 上传前同名/同内容预检 |
| POST | `/api/file/instant` | `{parent_id?, department_id?, file_name, file_size, file_hash}` | 跨用户秒传；返回 `{instant: true/false, ...}` |
| POST | `/api/file/chunk/init` | `{parent_id?, department_id?, file_name, file_size, file_hash?, chunk_size?}` | 初始化/恢复分片会话（幂等，24h 有效） |
| POST | `/api/file/chunk/upload` | multipart：`chunk`、`upload_id`、`index`、`chunk_hash?` | 上传单分片（重复序号幂等覆盖） |
| POST | `/api/file/chunk/complete` | `{upload_id}` | 合并全部分片并完成上传 |
| POST | `/api/file/chunk/abort` | `{upload_id}` | 取消并清理暂存 |
| GET | `/api/file/chunk/status` | `?upload_id=` | 查询已收分片（断点恢复） |

### 排他编辑锁（v1.2.0，仅部门文件）

| 方法 | 路径 | 请求 | 说明 |
|------|------|------|------|
| POST | `/api/file/lock/acquire` | `{id}` | 抢锁（幂等，重复获取=续约；冲突返回 `3501` + 持有者） |
| POST | `/api/file/lock/heartbeat` | `{id}` | 心跳续约（TTL 2 分钟） |
| POST | `/api/file/lock/release` | `{id, force?}` | 释放；管理员 `force:true` 可释放他人锁 |
| GET | `/api/file/lock/status` | `?id=` | 查询锁状态 |

### 回收站与历史版本（v1.3.0）

| 方法 | 路径 | 请求 | 说明 |
|------|------|------|------|
| GET | `/api/file/trash` | `?scope=personal\|department&department_id=` | 回收站列表（含删除人、剩余天数） |
| POST | `/api/file/trash/restore` | `{id}` | 按原位置还原 |
| DELETE | `/api/file/trash/item` | `{id}` | 单条彻底删除 |
| DELETE | `/api/file/trash` | `?scope=&department_id=` | 清空回收站，返回 `{count}` |
| GET | `/api/file/versions/<node_id>` | — | 版本列表 + 当前版本信息 |
| GET | `/api/file/version/download` | `?version_id=` | 下载历史版本（文件名带时间戳） |
| POST | `/api/file/version/restore` | `{version_id}` | 一键恢复（恢复动作自身留版本） |

## 分享（share）

| 方法 | 路径 | 权限 | 请求 | 说明 |
|------|------|------|------|------|
| POST | `/api/share/create` | 登录 | `{file_id, password?, expire_days}` | 创建分享；有效期仅 0/1/7/30 天；密码 1–32 位 |
| GET | `/api/share/info` | 公开 | `?code=` | 分享脱敏信息（浏览数 +1） |
| POST | `/api/share/verify-password` | 公开 | `{code, password}` | 校验密码，签发访问令牌；错误限流（`4106`） |
| GET | `/api/share/list` | 登录 | `?page=&size=&keyword=` | 我的分享列表 |
| DELETE | `/api/share/cancel` | 登录 | `?id=`（或 JSON `{id}`） | 取消分享 |
| GET | `/api/share/download` | 公开（令牌） | `?code=&token=` | 匿名下载（加密分享需 verify 换取的 token）；支持 Range |

## 部门管理（department）

> 功能未开启时本节全部返回 HTTP 403、业务码 `4030`。

| 方法 | 路径 | 权限 | 请求 | 说明 |
|------|------|------|------|------|
| GET | `/api/department/tree` | 登录 | — | 按权限过滤的部门树 |
| POST | `/api/department` | 登录（根部门需超管） | `{name, parent_id?}` | 新增部门 |
| PUT | `/api/department/<id>` | 超管/部门管理员 | `{name?, sort_order?, storage_quota?}` | 更新（配额仅超管，0=不限额） |
| DELETE | `/api/department/<id>` | 超管/部门管理员 | — | 删除（非空返回 `3310`） |
| POST | `/api/department/<id>/move` | 超管 | `{new_parent_id}` | 迁移 |
| GET | `/api/department/<id>/members` | 超管/部门管理员 | — | 成员列表 |
| GET | `/api/department/<id>/candidate-users` | 超管/部门管理员 | `?keyword=` | 可添加用户候选（≤20 条） |
| POST | `/api/department/<id>/members` | 超管/部门管理员 | `{user_id, position?}` | 添加成员 |
| PUT | `/api/department/<id>/members/<user_id>` | 超管/部门管理员 | `{position}` | 更新职位 |
| DELETE | `/api/department/<id>/members/<user_id>` | 超管/部门管理员 | — | 移除成员 |

## 权限管理（permission）

> 功能未开启时同上返回 `4030`。

| 方法 | 路径 | 权限 | 请求 | 说明 |
|------|------|------|------|------|
| POST | `/api/permission/admin` | 超管/上级管理员 | `{department_id, user_id, scope}` | 委派部门管理员；`scope` = `self` / `self_and_sub` |
| DELETE | `/api/permission/admin/<dept_id>/<user_id>` | 超管/上级管理员 | — | 撤销管理员 |
| GET | `/api/permission/admins/<dept_id>` | 登录 | — | 部门管理员列表 |
| POST | `/api/permission/grant` | 超管/部门管理员 | `{user_id, department_id, folder_id?, permission, expire_time?}` | 授予 `read_only`/`read_write`/`denied`，可带文件夹与到期时间 |
| DELETE | `/api/permission/<perm_id>` | 超管/部门管理员 | — | 撤销权限 |
| GET | `/api/permission/department/<dept_id>` | 超管/部门管理员 | — | 部门授权明细 |
| GET | `/api/permission/my` | 登录 | — | 我的权限 |
| GET | `/api/permission/my-admin-depts` | 登录 | — | 我被委派管理的部门（前端权限感知） |

## 审计日志（log）

| 方法 | 路径 | 权限 | 参数 | 说明 |
|------|------|------|------|------|
| GET | `/api/log/global` | 超管 | `?page=&size=&action=&department_id=&user_id=` | 全局操作日志 |
| GET | `/api/log/department/<dept_id>` | 部门管理员 | `?page=&size=&action=&user_id=` | 部门及子部门日志 |

## 插件（plugin）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/plugin/file/stream` | 归属 JWT 或分享 `code+token` | 内联文件流（预览），支持 Range；`?id=`（归属）或 `?code=&token=`（分享），可选 `?plugin=` 走插件权限钩子；Range seek 不记下载日志 |
| POST | `/api/plugin/file/save` | 登录（归属者） | 编辑保存回调：JSON `{id, content}` 或 multipart `file`；重新走类型/配额校验，临时文件原子覆盖 |
| GET | `/api/plugin/auth/check` | 归属 JWT 或分享 | 返回访问身份、文件信息与该后缀可用插件 |
| GET | `/api/plugin/available` | 登录 | `?suffix=` 按后缀查询已启用插件 |
| POST | `/api/plugin/register` | 超管 | `{name?}` 重扫描注册表（可顺带启用） |
| GET | `/api/plugin/list` | 超管 | 插件列表 + 已加载 + 扫描错误 |
| PUT | `/api/plugin/<name>/enabled` | 超管 | `{enabled: bool}` 启用/禁用 |

## 管理员（admin）

| 方法 | 路径 | 权限 | 请求 | 说明 |
|------|------|------|------|------|
| GET | `/api/admin/metrics` | 超管 | — | 监控仪表盘指标（CPU/内存/磁盘/在线/流量/存储） |
| POST | `/api/admin/backup` | 超管 | — | 立即备份（后台执行，返回 `{status:"running"}`；并发返回 `3601`） |
| POST | `/api/admin/backup/test-connection` | 超管 | `{backup_protocol, backup_host, backup_port, backup_username, backup_password, backup_remote_dir}` | 测试远端连通性，仅测试不保存 |
| GET | `/api/admin/backups` | 超管 | — | `{items, running}` 备份列表（记录与实际文件合并） |
| GET | `/api/admin/backup/download/<record_id>` | 超管 | — | 下载备份 zip（远端记录服务端先拉取） |
| DELETE | `/api/admin/backup/<record_id>` | 超管 | — | 删除备份（本地/远端文件 + 记录） |
| POST | `/api/admin/backup/restore` | 超管 | multipart `file`（上传 zip）或 JSON `{backup_id}` / `{remote_filename}`；`confirm` 必须为 `true` | 恢复；成功 2 秒后进程退出由守护拉起 |

## 业务错误码总表

> 完整的业务码一览（含触发场景与处理建议）见 [业务码一览](./11-Business-Codes.md)；本节表格保留作为 API 页的就近参考。
>
> HTTP 状态码与业务码独立：4xx/5xx 为 HTTP 状态，`code` 为业务码。未标注 HTTP 状态的默认 400。

### 通用 / 认证

| 码 | 含义 | HTTP |
|----|------|------|
| 0 | 成功 | 200 |
| 4001 | 系统尚未安装，请先完成安装向导 | 503 |
| 4010 | 请先登录 | 401 |
| 4011 | 登录已过期，请重新登录 | 401 |
| 4012 | 无效的登录凭证 | 401 |
| 4013 | 登录状态已失效（token 被吊销） | 401 |
| 4014 | 用户不存在或账号不可用 | 401 |
| 4030 | 需要管理员权限；或「部门网盘功能未开启」 | 403 |
| 4031 | 账号已被禁用 | 403 |
| 4032 | 无权访问该资源/操作 | 403 |
| 4040 | 资源不存在 | 404 |
| 4050 | 请求方法不被允许 | 405 |
| 4130 | 上传文件超过大小限制 | 413 |
| 5000 | 服务器内部错误 | 500 |

### 账号与设置

| 码 | 含义 |
|----|------|
| 1001 | 用户名需为 3-32 位中英文、数字、下划线或连字符 |
| 1002 | 邮箱格式不正确 |
| 1003 | 密码长度需为 8-64 位 |
| 1004 | 密码须同时包含字母和数字 |
| 1100 | 系统当前未开放注册 |
| 1101 | 用户名或邮箱已被注册/已存在 |
| 1102 | 请输入用户名和密码 |
| 1103 | 用户名或密码错误 |
| 1201 | 原密码不正确 |
| 1202 | 新密码不能与原密码相同 |
| 1203 | 存储配额必须为正整数字节 |
| 1204 | 用户不存在 |
| 1205 | 新配额不能小于该用户已使用空间 |
| 1206 | 非法的账号状态 |
| 1209 | 角色必须为 admin 或 user |
| 1210 | 不能修改自己的角色/启用状态 |
| 1211 | 至少需要保留一个启用状态的管理员 |
| 1213 | 请通过个人中心修改自己的密码 |
| 1220 | allow_register 必须为布尔值 |
| 1221 | 设置项类型错误（必须为整数/布尔/字符串） |
| 1222 | 设置项取值越界或枚举非法（含 backup_target/protocol/port） |
| 1223 | 远端备份必须填写服务器地址 |

| 码 | 含义 |
|----|------|
| 2001 | 不支持的数据库类型 |
| 2002 | SQLite 文件名不合法 |
| 2003 | 请完整填写数据库主机、库名和账号 |
| 2004 | 数据库端口不合法 |
| 2005 | 无法识别的数据库连接串 |
| 2006 | 数据库驱动缺失 |
| 2007 | 数据库连接或写权限校验失败 |
| 2008 | 存储目录不可写 |
| 2009 | 目标数据库已存在用户数据，拒绝覆盖安装 |
| 2010 | 安装配置写入失败 |
| 2020 | 系统已安装，安装向导已锁定 |

> HTTP 例外：`2020` 返回 403；本节其余码均为 400。

### 存储与文件

| 码 | 含义 | 备注 |
|----|------|------|
| 3001 | 非法的存储路径 | |
| 3002 | 文件名不合法 | |
| 3003 | 文件/分片保存失败 | |
| 3004 | 文件路径缺失 | |
| 3005 | 非法的文件访问路径 | |
| 3006 | 非法的文件指纹 | |
| 3101 | 文件/文件夹不存在 | 404 |
| 3102 | 目标不是文件夹 | |
| 3103 | 同级目录下已存在同名文件或文件夹 | 409 |
| 3104 | 文件名过长/不合法 | |
| 3105 | 禁止上传/保存该后缀类型 | |
| 3106 | 存储空间不足，上传/保存被拒绝 | 413 |
| 3107 | 同名文件夹已存在 / 同名文件过多 | |
| 3108 | 不能覆盖文件夹 / 不能移动到自身或其子文件夹内 | |
| 3109 | 不能在个人空间与部门网盘之间移动文件 | 409 |
| 3201 | 未选择上传文件 / 缺少分片数据 | |
| 3202 | 缺少文件名或文件 id / 文件大小非法 / 超过最大允许大小 | 部分场景 413 |
| 3203 | 文件夹暂不支持打包下载 | |
| 3204 | 物理文件已丢失 | 410 |
| 3205 | 文件指纹校验失败，上传可能损坏 | |
| 3206 | 缺少合法的文件指纹 | |
| 3207 | 上传会话不存在/已结束/已过期，或缺 upload_id | 部分场景 404 |
| 3208 | 分片序号缺失/非法/大小不符 | |
| 3209 | 分片指纹校验失败 | |
| 3210 | 分片不完整/总大小不一致/缺失，无法合并 | |
| 3211 | 文件物理块缺失，请重新上传 | |

### 分享

| 码 | 含义 | HTTP |
|----|------|------|
| 4101 | 分享不存在或已失效 | 404 |
| 4102 | 分享已过期 | 403 |
| 4103 | 分享已被取消 | 403 |
| 4104 | 需要访问密码 / 访问凭证缺失、过期、无效或不匹配 | 403 |
| 4105 | 访问密码错误 | 403 |
| 4106 | 尝试过于频繁（同码同 IP 限流，msg 含重试秒数） | 429 |
| 4107 | 分享的文件已被删除 | 410 |
| 4108 | 分享不存在或无权操作（取消分享时） | 404 |
| 4109 | 有效期选项不合法（仅 0/1/7/30） | |
| 4110 | 分享码生成失败，请重试 | 500 |
| 4111 | 文件夹暂不支持下载 | |
| 4112 | 分享密码长度需为 1-32 位 | |

### 版本 / 排他锁 / 回收站

| 码 | 含义 | HTTP |
|----|------|------|
| 3501 | 文件正被他人编辑（锁冲突），data 含持有者 | 409 |
| 3502 | 文件未被锁定 / 只有锁持有者可以释放该锁 | 409 |
| 3503 | 个人文件不支持编辑锁 | 400 |
| 3510 | 历史版本功能已关闭，无法恢复版本 | |
| 3511 | 历史版本不存在 / 原文件不存在或已删除 | 404 |
| 3512 | 文件内容缺失，无法恢复 | |
| 3513 | 缺少版本 id | |
| 3514 | 历史版本物理文件已丢失 | 410 |
| 3520 | 回收站条目不存在 | 404 |
| 3521 | 无法还原：同名文件过多 / 原位置已不存在 | 409 / 410 |

### 部门与权限

| 码 | 含义 | HTTP |
|----|------|------|
| 3301 | 部门不存在 / 缺少部门参数 | 404 |
| 3302 | 无权管理该部门 / 仅超管可执行该操作 | 403 |
| 3303 | 部门名称不能为空或过长 | |
| 3304 | 同级已存在同名部门 | 409 |
| 3305 | 仅超管可调整配额 / 不能移动到自身或其子部门下 | 403 / 409 |
| 3306 | 部门配额非法（为负或低于已用）/ 用户不存在 | |
| 3307 | 该用户已被禁用，不能加入部门 | |
| 3308 | 该用户已是部门成员 | 409 |
| 3309 | 该用户不是部门成员 | 404 |
| 3310 | 部门（含子部门）下仍存在文件/文件夹，禁止删除 | 409 |
| 3401 | scope 必须为 self 或 self_and_sub | |
| 3402 | 无权委派/撤销该部门的管理员 | 403 |
| 3403 | 用户不存在 | 404 |
| 3404 | 该用户不是部门管理员 | 404 |
| 3405 | 权限类型不合法（read_only/read_write/denied） | |
| 3406 | 目标文件夹不存在或不是文件夹 | 404 |
| 3407 | 文件夹不属于该部门 | 409 |
| 3408 | 权限记录不存在 | 404 |

### 插件与备份

| 码 | 含义 | HTTP |
|----|------|------|
| 5101 | 插件不存在 / 插件源码未找到 | 404 |
| 5102 | 插件未启用或已被禁用 | 403 |
| 5103 | 插件启用失败 | 500 |
| 5104 | enabled 必须为布尔值 | |
| 5201 | 缺少文件参数（id 或 code+token） | 400 |
| 5202 | 文件夹不支持流读取 | |
| 5203 | 保存内容不合法（为空/类型错误/写失败） | |
| 5204 | 该插件不支持此文件类型 | |
| 5205 | 插件权限钩子拒绝了本次操作 | 403 |
| 3601 | 已有备份任务正在执行 | 409 |
| 3602 | 备份/恢复失败（通用） | 400 |
| 3603 | 远端连接失败/认证失败 | 400 |
| 3604 | 备份不存在 | 404 |
| 3605 | 备份包校验失败（坏包/被篡改） | 400 |
| 3606 | 数据库类型暂不支持（PostgreSQL） | 400 |
| 3607 | 未勾选恢复风险确认 | 400 |

## 相关页面

- [配置参考（环境变量/设置键/定时任务）](./08-Configuration.md)
- [个人网盘使用（上传机制细节）](./02-Personal-Drive.md)
- [常见问题](./10-FAQ.md)
- [个人网盘使用（上传机制细节）](./02-Personal-Drive.md)
- [常见问题](./10-FAQ.md)
- [个人网盘使用（上传机制细节）](./02-Personal-Drive.md)
- [常见问题](./10-FAQ.md)
