"""CPU 采样任务：每 15 秒更新一次 cgroup/psutil CPU 使用率。"""
from ..services import metrics_service


def run() -> dict:
    sample = metrics_service.sample_cpu()
    return {"cpu_percent": sample["percent"]}
