#!/usr/bin/env bash
# ============================================================
# zhyCloudDisk Docker 一键部署脚本
# 用法：./deploy.sh <命令>
#   init     从 .env.example 生成 .env（已存在则跳过）
#   up       构建镜像并后台启动（默认命令），随后做健康检查
#   down     停止并移除容器（数据卷保留）
#   restart  重启全部服务
#   status   查看容器状态
#   logs     跟踪全部服务日志（Ctrl+C 退出）
#   update   拉取最新代码后重新构建并滚动更新
#   shell    进入后端容器（排障用）
# ============================================================
set -euo pipefail

cd "$(dirname "$0")"

ENV_FILE=".env"
ENV_EXAMPLE=".env.example"

# ---------- 输出辅助 ----------
info()  { printf '\033[1;34m[INFO]\033[0m  %s\n' "$*"; }
ok()    { printf '\033[1;32m[OK]\033[0m    %s\n' "$*"; }
warn()  { printf '\033[1;33m[WARN]\033[0m  %s\n' "$*"; }
error() { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; }

# ---------- 依赖检查 ----------
ensure_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        error "未检测到 docker，请先安装 Docker：https://docs.docker.com/engine/install/"
        exit 1
    fi
    if ! docker info >/dev/null 2>&1; then
        error "Docker 守护进程未运行，请先启动 Docker（systemctl start docker）。"
        exit 1
    fi
    if docker compose version >/dev/null 2>&1; then
        COMPOSE=(docker compose)
    elif command -v docker-compose >/dev/null 2>&1; then
        COMPOSE=(docker-compose)
    else
        error "未检测到 docker compose 插件，请安装 Compose v2。"
        exit 1
    fi
}

ensure_env() {
    if [ ! -f "$ENV_FILE" ]; then
        if [ ! -f "$ENV_EXAMPLE" ]; then
            error "缺少 $ENV_EXAMPLE，请确认部署文件完整。"
            exit 1
        fi
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        info "已从 $ENV_EXAMPLE 生成 $ENV_FILE，请按需修改（尤其是管理员密码）后重新执行：./deploy.sh up"
        exit 0
    fi
}

# 从 .env 读取变量（兼容 export 与纯 KEY=VALUE）
env_val() {
    local key="$1" default="$2"
    local val
    val=$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true)
    echo "${val:-$default}"
}

# ---------- 健康检查 ----------
wait_healthy() {
    local web_port
    web_port=$(env_val ZHY_WEB_PORT 8080)
    local url="http://127.0.0.1:${web_port}/api/ping"
    local max_wait=90 interval=3 elapsed=0

    info "等待服务就绪：$url（最长 ${max_wait}s）"
    while [ "$elapsed" -lt "$max_wait" ]; do
        local body=""
        if command -v curl >/dev/null 2>&1; then
            body=$(curl -fsS --max-time 5 "$url" 2>/dev/null || true)
        elif command -v wget >/dev/null 2>&1; then
            body=$(wget -qO- --timeout=5 "$url" 2>/dev/null || true)
        else
            warn "未安装 curl/wget，跳过健康检查。"
            return 0
        fi
        if echo "$body" | grep -q '"code":0'; then
            ok "后端已就绪：$body"
            return 0
        fi
        sleep "$interval"
        elapsed=$((elapsed + interval))
        printf '.'
    done
    echo
    error "服务在 ${max_wait}s 内未就绪，请查看日志：./deploy.sh logs"
    "${COMPOSE[@]}" ps
    exit 1
}

security_hints() {
    local pw
    pw=$(env_val ZHY_ADMIN_PASSWORD "")
    if [ "$pw" = "Admin12345" ]; then
        warn "管理员密码仍为示例值 Admin12345，公网部署前请务必修改 .env（仅首次安装生效）。"
    fi
    local cors
    cors=$(env_val ZHY_CORS_ORIGINS "*")
    if [ "$cors" = "*" ]; then
        warn "CORS 当前允许所有来源（*）；公网部署建议在 .env 中限定 ZHY_CORS_ORIGINS。"
    fi
}

# ---------- 部署方式提示 ----------
show_deploy_note() {
    info "镜像内置 MySQL + Redis，首次启动自动完成安装（创建数据库与超管账号）。"
    info "如需跳过安装向导并直接设置管理员，请在 .env 中配置 ZHY_ADMIN_USERNAME 与 ZHY_ADMIN_PASSWORD。"
}

# ---------- 命令 ----------
cmd_init() {
    if [ -f "$ENV_FILE" ]; then
        warn "$ENV_FILE 已存在，无需重复初始化。"
        exit 0
    fi
    ensure_env
}

cmd_up() {
    ensure_docker
    ensure_env
    show_deploy_note
    security_hints
    info "构建镜像并启动服务..."
    "${COMPOSE[@]}" up -d --build
    wait_healthy
    "${COMPOSE[@]}" ps
    local web_port
    web_port=$(env_val ZHY_WEB_PORT 8080)
    ok "部署完成：浏览器访问 http://<服务器IP>:${web_port}"
    ok "桌面客户端服务器地址填写同一个地址（无需 /api 后缀）。"
}

cmd_down()   { ensure_docker; "${COMPOSE[@]}" down; ok "已停止（数据卷保留）。"; }
cmd_restart(){ ensure_docker; ensure_env; "${COMPOSE[@]}" restart; wait_healthy; "${COMPOSE[@]}" ps; }
cmd_status() { ensure_docker; "${COMPOSE[@]}" ps; }
cmd_logs()   { ensure_docker; "${COMPOSE[@]}" logs -f --tail=200; }
cmd_update() {
    ensure_docker
    ensure_env
    if command -v git >/dev/null 2>&1 && [ -d .git ]; then
        info "拉取最新代码..."
        git pull --ff-only
    else
        warn "非 git 工作副本，跳过拉取，直接重建镜像。"
    fi
    "${COMPOSE[@]}" up -d --build
    wait_healthy
    "${COMPOSE[@]}" ps
    ok "更新完成。"
}
cmd_shell()  { ensure_docker; "${COMPOSE[@]}" exec app bash; }

case "${1:-up}" in
    init)    cmd_init ;;
    up|start)     cmd_up ;;
    down|stop)    cmd_down ;;
    restart) cmd_restart ;;
    status|ps)    cmd_status ;;
    logs)    cmd_logs ;;
    update|upgrade) cmd_update ;;
    shell)   cmd_shell ;;
    *)
        error "未知命令：$1"
        sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
        exit 1
        ;;
esac
