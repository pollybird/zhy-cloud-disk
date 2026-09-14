"""统一 JSON 响应封装：{code, msg, data}。code=0 表示成功。"""
from flask import jsonify


def success(data=None, msg: str = "ok"):
    return jsonify({"code": 0, "msg": msg, "data": data}), 200


def fail(msg: str, code: int = 1, http_status: int = 400, data=None):
    return jsonify({"code": code, "msg": msg, "data": data}), http_status
