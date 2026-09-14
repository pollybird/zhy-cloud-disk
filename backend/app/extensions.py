"""Flask 扩展单例。"""
from apscheduler.schedulers.background import BackgroundScheduler
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
jwt = JWTManager()
cors = CORS()

# APScheduler 单例（后台调度器，安装完成后启动）
scheduler = BackgroundScheduler(timezone="UTC")
