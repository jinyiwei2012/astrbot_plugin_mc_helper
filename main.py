"""AstrBot 插件：Minecraft 错误报告分析"""

import asyncio
import copy
import json
import shutil
from typing import Any, Optional
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import File
from astrbot.api.star import Context, Star, StarTools

from .lib._solutions import load_db, load_duplicate_mods, get_solution, count_solutions
from .lib._security import UserBlacklist
from .lib._handlers import Handlers


class McHelperPlugin(Star):
    """插件入口，将所有命令和消息处理委托给 Handlers"""

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config

        # 数据存储根目录
        self.store_path = StarTools.get_data_dir("astrbot_plugin_mc_helper")
        self.store_path.mkdir(parents=True, exist_ok=True)
        # 方案库写入的并发锁
        self._lock = asyncio.Lock()
        # 标记用户配置是否需要退出时持久化
        self._config_dirty = False

        # 首次运行时将默认方案库复制到数据目录
        src = Path(__file__).parent / "data" / "solutions.json"
        self.db_path = self.store_path / "solutions.json"
        if not self.db_path.exists() and src.exists():
            shutil.copy2(src, self.db_path)

        self.solutions = load_db(self.db_path)
        self.dup_data = load_duplicate_mods(Path(__file__).parent / "data" / "duplicate_mods.json")
        self.blacklist = UserBlacklist(self.store_path / "user_blacklist.json")
        self.reports_path = self.store_path / "错误报告"
        self.reports_path.mkdir(parents=True, exist_ok=True)
        self.user_cfg_path = self.store_path / "user_config.json"
        self.user_configs: dict = self._load_user_configs()
        # 每个会话最近看到的文件（用于 /mc_check 降级）
        self.recent: dict[str, File] = {}
        self.handlers = Handlers(self)

        logger.info(
            f"MC Helper 已加载，方案库共 {count_solutions(self.solutions)} 条，配置项 {len(config) if config else 0} 个"
        )

    def _cfg(self, key: str, default: Any) -> Any:
        """从 astrbot 的 astr_bot.json 读取插件级配置项"""
        if self.config and key in self.config:
            return self.config[key]
        return default

    def _is_allowed(self, event: AstrMessageEvent) -> bool:
        """检查群组是否在白名单中"""
        wl = self._cfg("whitelist_groups", [])
        if not wl or not isinstance(wl, (list, tuple, set)):
            return True
        return event.get_group_id() in wl

    async def get_solution(self, key: str) -> Optional[str]:
        """线程安全的方案查询"""
        async with self._lock:
            return get_solution(self.solutions, key)

    async def save_solution(self, key: str, solution: str, category: str):
        """通过临时文件 + 原子重命名安全保存方案"""
        async with self._lock:
            old = copy.deepcopy(self.solutions)
            try:
                if category not in self.solutions:
                    self.solutions[category] = {}
                self.solutions[category][key] = {"solution": solution}
                # 先写 .tmp 再重命名，防止写入中断损坏文件
                tmp_path = self.db_path.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self.solutions, f, ensure_ascii=False, indent=2)
                tmp_path.replace(self.db_path)
            except Exception as e:
                self.solutions = old
                logger.error(f"保存方案库失败: {e}")

    # ── 用户配置 ──

    def _load_user_configs(self) -> dict:
        try:
            if self.user_cfg_path.exists():
                with open(self.user_cfg_path, "r", encoding="utf-8") as f:
                    return dict(json.load(f))
        except Exception as e:
            logger.error(f"加载用户配置失败: {e}")
        return {}

    def _save_user_configs(self):
        """将用户配置持久化到磁盘"""
        try:
            with open(self.user_cfg_path, "w", encoding="utf-8") as f:
                json.dump(self.user_configs, f, ensure_ascii=False, indent=2)
            self._config_dirty = False
        except Exception as e:
            logger.error(f"保存用户配置失败: {e}")

    def get_user_cfg(self, uid: str, key: str, default: Any) -> Any:
        return self.user_configs.get(uid, {}).get(key, default)

    def set_user_cfg(self, uid: str, key: str, value: Any) -> None:
        if uid not in self.user_configs:
            self.user_configs[uid] = {}
        self.user_configs[uid][key] = value
        self._config_dirty = True

    # ── 命令分发 ──

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        async for r in self.handlers.on_message(event):
            yield r

    @filter.command("mc_help")
    async def mc_help(self, event: AstrMessageEvent):
        async for r in self.handlers.mc_help(event):
            yield r

    @filter.command("mc_check")
    async def mc_check(self, event: AstrMessageEvent, error_text: str = ""):
        async for r in self.handlers.mc_check(event, error_text):
            yield r

    @filter.command("mc_add_solution")
    async def mc_add_solution(self, event: AstrMessageEvent):
        async for r in self.handlers.mc_add_solution(event):
            yield r

    @filter.command("mc_reports")
    async def mc_reports(self, event: AstrMessageEvent):
        async for r in self.handlers.mc_reports(event):
            yield r

    @filter.command("mc_config")
    async def mc_config(self, event: AstrMessageEvent, args: str = ""):
        async for r in self.handlers.mc_config(event, args):
            yield r

    async def terminate(self):
        """退出时将脏的用户配置写入磁盘"""
        if self._config_dirty:
            self._save_user_configs()
        logger.info("MC Helper 已卸载")
