FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 系统依赖（bcrypt 编译需要 gcc + libc-dev）
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libc-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 实例目录与存储目录由 volume 挂载，此处仅确保存在
RUN mkdir -p /app/instance /app/storage

EXPOSE 5000

# gunicorn 生产入口：wsgi:application（wsgi.py 中 maybe_auto_install 支持环境变量静默安装）
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "--access-logfile", "-", "--error-logfile", "-", "wsgi:application"]
