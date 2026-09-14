"""PluginManager：插件发现、注册、启停、冲突检测与状态持久化。

- 发现范围：backend/app/plugins/builtin（内置）与项目根 plugins/（外部投放目录），
  由 config["PLUGIN_DIRS"] 提供。
- 每个插件文件/包必须导出模块级 `plugin` 实例或 `get_plugin()` 工厂。
- 注册表同步：发现结果与 PluginRecord 对账（新增/更新元信息/删除已消失项），
  启用状态持久化在数据库，重启不丢失。
- 冲突检测：同名插件以先发现者为准，后者跳过并记录错误。
- 异常隔离：单个插件加载失败不阻断主进程，记录 last_error 并自动保持禁用。
"""
from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path

from flask import Flask

from ..extensions import db
from ..models.plugin import PluginRecord
from .base import BasePlugin, PluginMetaError

logger = logging.getLogger("plugin")

Discovered = list[tuple[BasePlugin, str, Path]]  # [(实例, 来源, 路径)]


class PluginManager:
    def __init__(self) -> None:
        self._plugins: dict[str, BasePlugin] = {}
        self._blueprints_registered: set[str] = set()
        self._scan_errors: list[str] = []
        self._last_discovered: Discovered = []

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def is_enabled(self, name: str) -> bool:
        """查询插件是否已启用：内存优先，多 worker 间通过缓存兜底。"""
        if name in self._plugins:
            return True
        # 多 worker 场景：其他进程可能已启用该插件，查缓存确认
        from ..services.cache_service import cache_exists

        return cache_exists(f"plugin:enabled:{name}")

    def get(self, name: str) -> BasePlugin | None:
        return self._plugins.get(name)

    def loaded_names(self) -> list[str]:
        return list(self._plugins.keys())

    def scan_errors(self) -> list[str]:
        return list(self._scan_errors)

    def available_for_suffix(self, suffix: str) -> list[dict]:
        """返回已启用且声明支持该后缀的插件元信息（按发现顺序）。"""
        suffix = (suffix or "").lower().lstrip(".")
        if not suffix:
            return []
        return [
            p.meta()
            for p in self._plugins.values()
            if suffix in p.supported_exts
        ]

    # ------------------------------------------------------------------
    # 发现与同步
    # ------------------------------------------------------------------
    def discover_and_sync(self, app: Flask) -> list[BasePlugin]:
        """扫描插件目录 → 对账注册表 → 加载所有已启用插件。返回加载成功列表。"""
        with app.app_context():
            self._last_discovered = self._scan_dirs(app)
            self._sync_registry(self._last_discovered)
            self._load_enabled(app)
            return list(self._plugins.values())

    def _scan_dirs(self, app: Flask) -> Discovered:
        """扫描全部插件目录；冲突/损坏跳过并记录到 _scan_errors。"""
        self._scan_errors = []
        found: Discovered = []
        seen_names: dict[str, Path] = {}

        dirs = app.config.get("PLUGIN_DIRS") or []
        # 第一层目录视为内置，其余视为外部
        for idx, raw in enumerate(dirs):
            source = "builtin" if idx == 0 else "external"
            root = Path(raw)
            if not root.is_dir():
                continue
            for entry in sorted(root.iterdir()):
                if entry.name.startswith(("_", ".")) or entry.name == "__pycache__":
                    continue
                result = self._load_module_from_entry(entry)
                if isinstance(result, str):
                    self._scan_errors.append(f"{entry.name}: {result}")
                    continue
                instance, origin = result
                # 冲突检测：同名以先发现者为准
                if instance.name in seen_names:
                    self._scan_errors.append(
                        f"{entry.name}: 插件名 {instance.name!r} 与 "
                        f"{seen_names[instance.name].name} 冲突，已跳过"
                    )
                    continue
                seen_names[instance.name] = entry
                found.append((instance, source, origin))
        return found

    def _load_module_from_entry(
        self, entry: Path
    ) -> tuple[BasePlugin, Path] | str:
        """从单文件 .py 或包目录加载插件实例；失败返回错误说明字符串。"""
        try:
            if entry.is_file() and entry.suffix == ".py":
                module_name = f"zhy_plugin_{entry.stem}"
                spec = importlib.util.spec_from_file_location(module_name, entry)
                if spec is None or spec.loader is None:
                    return "无法解析模块"
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                origin = entry
            elif entry.is_dir() and (entry / "__init__.py").is_file():
                module_name = f"zhy_plugin_{entry.name}"
                spec = importlib.util.spec_from_file_location(
                    module_name,
                    entry / "__init__.py",
                    submodule_search_locations=[str(entry)],
                )
                if spec is None or spec.loader is None:
                    return "无法解析包模块"
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                origin = entry
            else:
                return "跳过：既不是 .py 文件也不是 Python 包"
        except PluginMetaError as e:
            return str(e)
        except Exception as e:  # 异常隔离：插件损坏不影响主进程
            return f"加载失败：{e.__class__.__name__}: {e}"

        instance = self._extract_instance(module)
        if isinstance(instance, str):
            return instance
        return instance, origin

    @staticmethod
    def _extract_instance(module) -> BasePlugin | str:
        """模块级 `plugin` 实例优先，其次 `get_plugin()` 工厂，再次首个 BasePlugin 子类。"""
        candidate = getattr(module, "plugin", None)
        if candidate is None and hasattr(module, "get_plugin"):
            try:
                candidate = module.get_plugin()
            except Exception as e:
                return f"get_plugin() 执行失败：{e}"
        if candidate is None:
            subclasses = [
                obj
                for obj in vars(module).values()
                if isinstance(obj, type)
                and issubclass(obj, BasePlugin)
                and obj is not BasePlugin
            ]
            if subclasses:
                try:
                    candidate = subclasses[0]()
                except Exception as e:
                    return f"插件实例化失败：{e}"
        if candidate is None:
            return "缺少模块级 plugin 实例或 get_plugin() 工厂"
        if not isinstance(candidate, BasePlugin):
            return "导出的 plugin 不是 BasePlugin 子类实例"
        try:
            candidate.validate_meta()
        except PluginMetaError as e:
            return str(e)
        return candidate

    def _sync_registry(self, discovered: Discovered) -> None:
        """以发现结果对账 PluginRecord：新增/更新/删除，保留启用状态。"""
        rows = {r.name: r for r in db.session.query(PluginRecord).all()}
        discovered_names = set()

        for instance, source, _path in discovered:
            discovered_names.add(instance.name)
            row = rows.get(instance.name)
            exts = json.dumps(list(instance.supported_exts), ensure_ascii=False)
            if row is None:
                db.session.add(
                    PluginRecord(
                        name=instance.name,
                        version=instance.version,
                        author=instance.author,
                        description=instance.description,
                        supported_exts=exts,
                        preview_type=instance.preview_type,
                        source=source,
                        # 内置插件默认启用；外部插件默认禁用
                        enabled=source == "builtin",
                        last_error="",
                    )
                )
            else:
                row.version = instance.version
                row.author = instance.author
                row.description = instance.description
                row.supported_exts = exts
                row.preview_type = instance.preview_type
                row.source = source

        # 清理已消失（源码被移除）的插件记录
        for name, row in rows.items():
            if name not in discovered_names:
                db.session.delete(row)

        db.session.commit()

    def _load_enabled(self, app: Flask) -> None:
        """加载所有 enabled=True 的插件；失败自动置为禁用并记录错误。"""
        for name in list(self._plugins.keys()):
            self._unload(name)

        enabled_names = {
            r.name
            for r in db.session.query(PluginRecord)
            .filter(PluginRecord.enabled.is_(True))
            .all()
        }
        discovered = {
            inst.name: inst for inst, _source, _path in self._last_discovered
        }

        for name in sorted(enabled_names):
            instance = discovered.get(name)
            if instance is None:
                continue
            try:
                self._activate(app, instance)
                self._plugins[name] = instance
            except Exception as e:
                logger.exception("插件 %s 加载失败", name)
                row = (
                    db.session.query(PluginRecord)
                    .filter(PluginRecord.name == name)
                    .first()
                )
                if row is not None:
                    row.enabled = False
                    row.last_error = f"加载失败：{e.__class__.__name__}: {e}"
                    db.session.commit()

    def _activate(self, app: Flask, instance: BasePlugin) -> None:
        """调用插件 register 钩子并注册其自定义蓝图。"""
        instance.register(app)
        bp = instance.create_blueprint()
        if bp is not None and instance.name not in self._blueprints_registered:
            app.register_blueprint(bp, url_prefix=f"/api/plugin/ext/{instance.name}")
            self._blueprints_registered.add(instance.name)

    # ------------------------------------------------------------------
    # 启停
    # ------------------------------------------------------------------
    def enable(self, app: Flask, name: str) -> dict:
        """启用插件并返回其注册表 dict（在会话内序列化，避免 DetachedInstance）。"""
        from ..services.cache_service import cache_set

        with app.app_context():
            row = (
                db.session.query(PluginRecord)
                .filter(PluginRecord.name == name)
                .first()
            )
            if row is None:
                from ..utils.errors import ApiError

                raise ApiError("插件不存在", code=5101, http_status=404)
            if not row.enabled:
                instance = self._instance_by_name(name)
                try:
                    self._activate(app, instance)
                except Exception as e:
                    row.last_error = f"启用失败：{e.__class__.__name__}: {e}"
                    db.session.commit()
                    raise ApiError(f"插件启用失败：{e}", code=5103, http_status=500)
                self._plugins[name] = instance
                row.enabled = True
                row.last_error = ""
                db.session.commit()
                db.session.refresh(row)
            # 同步缓存，供其他 worker 感知
            cache_set(f"plugin:enabled:{name}", 1, ttl=0)
            return row.to_dict()

    def disable(self, app: Flask, name: str) -> dict:
        from ..services.cache_service import cache_delete

        with app.app_context():
            row = (
                db.session.query(PluginRecord)
                .filter(PluginRecord.name == name)
                .first()
            )
            if row is None:
                from ..utils.errors import ApiError

                raise ApiError("插件不存在", code=5101, http_status=404)
            if row.enabled:
                self._unload(name)
                row.enabled = False
                db.session.commit()
                db.session.refresh(row)
            # 同步缓存
            cache_delete(f"plugin:enabled:{name}")
            return row.to_dict()

    def _instance_by_name(self, name: str) -> BasePlugin:
        for inst, _source, _path in self._last_discovered:
            if inst.name == name:
                return inst
        from ..utils.errors import ApiError

        raise ApiError("插件源码未找到，请重新扫描", code=5101, http_status=404)

    def _unload(self, name: str) -> None:
        instance = self._plugins.pop(name, None)
        if instance is not None:
            try:
                instance.unload()
            except Exception:
                logger.exception("插件 %s unload 异常", name)

    # ------------------------------------------------------------------
    # 管理接口辅助
    # ------------------------------------------------------------------
    def list_records(self) -> list[dict]:
        rows = db.session.query(PluginRecord).order_by(PluginRecord.id.asc()).all()
        return [r.to_dict() for r in rows]

    def rescan(self, app: Flask) -> list[BasePlugin]:
        """重新扫描并同步注册表（保留既有启用状态），然后重载已启用插件。"""
        with app.app_context():
            self._last_discovered = self._scan_dirs(app)
            self._sync_registry(self._last_discovered)
            self._load_enabled(app)
            return list(self._plugins.values())


# 全局单例
manager = PluginManager()
