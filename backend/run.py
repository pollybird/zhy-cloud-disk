"""开发入口与命令行安装向导。

用法：
    python run.py            # 启动开发服务器
    python run.py setup      # 命令行交互式安装
"""
import getpass
import sys

from app import create_app
from app.services.setup_service import is_installed, maybe_auto_install, run_installation


def run_server() -> None:
    import os

    app = create_app()
    maybe_auto_install(app)
    host = os.environ.get("ZHY_HOST", "0.0.0.0")
    port = int(os.environ.get("ZHY_PORT", "5000"))
    debug = os.environ.get("ZHY_ENV", "production") == "development"
    app.run(host=host, port=port, debug=debug)


def run_cli_setup() -> None:
    app = create_app()
    if is_installed():
        print("系统已安装，安装向导已锁定。")
        return

    print("=== 钟毓私有云盘 · 命令行安装向导 ===")
    print("数据库类型：1) SQLite（默认，零配置）  2) MySQL  3) PostgreSQL")
    choice = input("请选择 [1]: ").strip() or "1"
    if choice == "1":
        payload = {"db_type": "sqlite", "database": "zhycloud.db"}
    elif choice == "2":
        payload = {
            "db_type": "mysql",
            "host": input("主机 [127.0.0.1]: ").strip() or "127.0.0.1",
            "port": input("端口 [3306]: ").strip() or "3306",
            "database": input("数据库名 [zhycloud]: ").strip() or "zhycloud",
            "username": input("用户名: ").strip(),
            "password": getpass.getpass("密码: "),
        }
    elif choice == "3":
        payload = {
            "db_type": "postgresql",
            "host": input("主机 [127.0.0.1]: ").strip() or "127.0.0.1",
            "port": input("端口 [5432]: ").strip() or "5432",
            "database": input("数据库名 [zhycloud]: ").strip() or "zhycloud",
            "username": input("用户名: ").strip(),
            "password": getpass.getpass("密码: "),
        }
    else:
        print("无效选择，退出。")
        sys.exit(1)

    storage_dir = input("存储目录（回车使用默认 storage/）: ").strip()
    if storage_dir:
        payload["storage_dir"] = storage_dir

    payload["admin_username"] = input("超级管理员用户名: ").strip()
    payload["admin_email"] = input("超级管理员邮箱: ").strip()
    while True:
        pwd = getpass.getpass("超级管理员密码（8-64 位，含字母和数字）: ")
        pwd2 = getpass.getpass("再次输入密码: ")
        if pwd == pwd2:
            payload["admin_password"] = pwd
            break
        print("两次输入不一致，请重试。")

    result = run_installation(app, payload)
    print(
        f"\n安装成功！超级管理员：{result['admin_username']}，"
        f"数据库：{result['db_type']}，存储目录：{result['storage_dir']}"
    )
    print("可执行 python run.py 启动服务。")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        run_cli_setup()
    else:
        run_server()
