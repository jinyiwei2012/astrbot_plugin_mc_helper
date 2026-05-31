import asyncio
import copy
import json
import shutil
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import File
from astrbot.api.star import Context, Star, StarTools

from .lib._solutions import load_db, load_duplicate_mods, get_solution, count_solutions
from .lib._security import UserBlacklist
from .lib._ai import ask_ai
from .lib._handlers import Handlers


class McHelperPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config

        self.store_path = StarTools.get_data_dir("astrbot_plugin_mc_helper")
        self.store_path.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._config_dirty = False

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
        self.recent: dict[str, File] = {}
        self.handlers = Handlers(self)

        logger.info(
            f"MC Helper 已加载，方案库共 {count_solutions(self.solutions)} 条，配置项 {len(config) if config else 0} 个"
        )

    def _cfg(self, key: str, default):
        if self.config and key in self.config:
            return self.config[key]
        return default

    def _is_allowed(self, event: AstrMessageEvent) -> bool:
        wl = self._cfg("whitelist_groups", [])
        if not wl:
            return True
        wl_set = wl if isinstance(wl, set) else set(wl)
        return event.get_group_id() in wl_set

    def get_solution(self, key: str):
        return get_solution(self.solutions, key)

    async def save_solution(self, key: str, solution: str, category: str):
        async with self._lock:
            old = copy.deepcopy(self.solutions)
            try:
                if category not in self.solutions:
                    self.solutions[category] = {}
                self.solutions[category][key] = {"solution": solution}
                with open(self.db_path, "w", encoding="utf-8") as f:
                    json.dump(self.solutions, f, ensure_ascii=False, indent=2)
            except Exception as e:
                self.solutions = old
                logger.error(f"保存方案库失败: {e}")

    async def ask_ai(self, event: AstrMessageEvent, text: str) -> str:
        return await ask_ai(self.context, event, text)

    # ── per-user config ──

    def _load_user_configs(self) -> dict:
        try:
            if self.user_cfg_path.exists():
                with open(self.user_cfg_path, "r", encoding="utf-8") as f:
                    return dict(json.load(f))
        except Exception as e:
            logger.error(f"加载用户配置失败: {e}")
        return {}

    def _save_user_configs(self):
        try:
            with open(self.user_cfg_path, "w", encoding="utf-8") as f:
                json.dump(self.user_configs, f, ensure_ascii=False, indent=2)
            self._config_dirty = False
        except Exception as e:
            logger.error(f"保存用户配置失败: {e}")

    def get_user_cfg(self, uid: str, key: str, default):
        return self.user_configs.get(uid, {}).get(key, default)

    def set_user_cfg(self, uid: str, key: str, value):
        if uid not in self.user_configs:
            self.user_configs[uid] = {}
        self.user_configs[uid][key] = value
        self._save_user_configs()

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
        logger.info("MC Helper 已卸载")
