# ====== Stage 1: 后端依赖 ======
FROM python:3.12-slim AS backend-build

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

WORKDIR /app

# 使用国内镜像源安装 apt 包
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends gcc libc-dev && \
    rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ====== Stage 2: 前端构建 ======
FROM node:20-slim AS frontend-build

WORKDIR /web
# 使用国内 npm 镜像加速依赖安装
RUN npm config set registry https://registry.npmmirror.com

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build


# ====== Stage 3: 最终镜像（MySQL + Redis + nginx + gunicorn） ======
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ZHY_INSTANCE_DIR=/app/instance \
    ZHY_STORAGE_DIR=/app/storage \
    ZHY_DOCKER=1

WORKDIR /app

# 使用国内镜像源安装 apt 包
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        mariadb-server \
        redis-server \
        nginx \
        supervisor \
        && rm -rf /var/lib/apt/lists/*

# 从 Stage 1 拷贝 Python 依赖
COPY --from=backend-build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=backend-build /usr/local/bin/gunicorn /usr/local/bin/gunicorn

# 拷贝后端代码
COPY backend/ .

# 拷贝前端构建产物（Stage 2 构建）
COPY --from=frontend-build /web/dist/ /usr/share/nginx/html/

# ---- MySQL 配置 ----
RUN mkdir -p /var/run/mysqld && chown mysql:mysql /var/run/mysqld && \
    printf '[mysqld]\n\
datadir=/var/lib/mysql\n\
socket=/var/run/mysqld/mysqld.sock\n\
pid-file=/var/run/mysqld/mysqld.pid\n\
user=mysql\n\
character-set-server=utf8mb4\n\
collation-server=utf8mb4_unicode_ci\n\
skip-networking=off\n\
bind-address=127.0.0.1\n' > /etc/mysql/mariadb.conf.d/50-docker.cnf && \
    # 初始化 MySQL 数据目录
    mysql_install_db --user=mysql --datadir=/var/lib/mysql

# ---- MySQL 初始化脚本（容器启动时执行一次） ----
RUN printf '#!/bin/bash\n\
set -e\n\
until mysqladmin ping --silent 2>/dev/null; do sleep 1; done\n\
mysql -u root -e "ALTER USER '"'"'root'"'"'@'"'"'localhost'"'"' IDENTIFIED VIA mysql_native_password; FLUSH PRIVILEGES;" 2>/dev/null || true\n\
mysql -u root -e "CREATE DATABASE IF NOT EXISTS zhycloud CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null || true\n\
touch /tmp/mysql-init-done\n\
' > /app/mysql-init.sh && chmod +x /app/mysql-init.sh

# ---- nginx 配置 ----
RUN printf 'server {\n\
    listen 80;\n\
    server_name _;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
\n\
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
\n\
    location /api/ {\n\
        proxy_pass         http://127.0.0.1:5000;\n\
        proxy_set_header   Host              $host;\n\
        proxy_set_header   X-Real-IP         $remote_addr;\n\
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;\n\
        proxy_set_header   X-Forwarded-Proto $scheme;\n\
        client_max_body_size 2g;\n\
        proxy_read_timeout   300s;\n\
        proxy_send_timeout   300s;\n\
    }\n\
\n\
    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$ {\n\
        expires 30d;\n\
        add_header Cache-Control "public, immutable";\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf && \
    rm -f /etc/nginx/sites-enabled/default

# ---- Redis 配置 ----
RUN sed -i 's/^bind 127.0.0.1/bind 127.0.0.1/' /etc/redis/redis.conf && \
    sed -i 's/^daemonize yes/daemonize no/' /etc/redis/redis.conf

# ---- supervisor 配置 ----
RUN printf '[supervisord]\n\
nodaemon=true\n\
logfile=/dev/stdout\n\
logfile_maxbytes=0\n\
\n\
[program:mysql]\n\
command=/usr/bin/mysqld_safe\n\
autostart=true\n\
autorestart=true\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0\n\
\n\
[program:redis]\n\
command=/usr/bin/redis-server /etc/redis/redis.conf\n\
autostart=true\n\
autorestart=true\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0\n\
\n\
[program:nginx]\n\
command=nginx -g "daemon off;"\n\
autostart=true\n\
autorestart=true\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0\n\
\n\
[program:gunicorn]\n\
command=gunicorn -w 1 -b 127.0.0.1:5000 --access-logfile - --error-logfile - wsgi:application\n\
directory=/app\n\
autostart=true\n\
autorestart=true\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0\n\
\n\
[program:mysql-init]\n\
command=bash -c "/app/mysql-init.sh && tail -f /dev/null"\n\
autostart=true\n\
autorestart=false\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0\n' > /etc/supervisor/conf.d/zhy.conf

RUN mkdir -p /app/instance /app/storage

VOLUME ["/app/storage", "/app/instance", "/var/lib/mysql"]

EXPOSE 80

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/zhy.conf"]
