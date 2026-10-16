"""生产 WSGI 入口（gunicorn）：gunicorn -w 2 -b 0.0.0.0:5000 wsgi:application"""
from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from app.services.setup_service import maybe_auto_install

application = create_app()

# L3：一体化镜像中 nginx 是唯一可信入口（单跳反向代理），
# 且 nginx 以覆盖方式设置 X-Forwarded-For（$remote_addr），
# 此处仅信任 1 跳，使 request.remote_addr / scheme / host 反映真实客户端。
application.wsgi_app = ProxyFix(
    application.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1
)

# 容器环境变量齐全时静默完成初始化
maybe_auto_install(application)
