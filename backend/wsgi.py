"""生产 WSGI 入口（gunicorn）：gunicorn -w 2 -b 0.0.0.0:5000 wsgi:application"""
from app import create_app
from app.services.setup_service import maybe_auto_install

application = create_app()

# 容器环境变量齐全时静默完成初始化
maybe_auto_install(application)
