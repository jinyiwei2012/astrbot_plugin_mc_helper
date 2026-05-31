import re
import os
import json
import zipfile
import shutil
from pathlib import Path
from typing import Optional

import aiohttp

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger
from astrbot.api.message_components import File, Reply
from astrbot.api import AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_data_path


class McHelperPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config

        plugin_data_path = Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_mc_helper"
        plugin_data_path.mkdir(parents=True, exist_ok=True)

        solutions_src = Path(__file__).parent / "data" / "solutions.json"
        self.solutions_db_path = plugin_data_path / "solutions.json"

        if not self.solutions_db_path.exists() and solutions_src.exists():
            shutil.copy2(str(solutions_src), str(self.solutions_db_path))

        self.solutions_db = self._load_solutions_db()
        self._recent_files: dict[str, File] = {}
        logger.info(f"MC Helper 插件已加载，本地方案库共 {self._count_solutions()} 条，配置项 {len(config) if config else 0} 个")

    def _cfg(self, key: str, default):
        if self.config and key in self.config:
            return self.config[key]
        return default

    def _load_solutions_db(self) -> dict:
        if self.solutions_db_path.exists():
            try:
                with open(self.solutions_db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载解决方案库失败: {e}")
        return {}

    def _get_solution(self, key: str) -> Optional[str]:
        for category, entries in self.solutions_db.items():
            if key in entries:
                entry = entries[key]
                return entry["solution"] if isinstance(entry, dict) else entry
        return None

    def _count_solutions(self) -> int:
        count = 0
        for v in self.solutions_db.values():
            if isinstance(v, dict):
                count += len(v)
            else:
                count += 1
        return count

    def _set_solution(self, key: str, solution: str, category: str = "AI生成"):
        if category not in self.solutions_db:
            self.solutions_db[category] = {}
        self.solutions_db[category][key] = {"solution": solution}
        try:
            with open(self.solutions_db_path, "w", encoding="utf-8") as f:
                json.dump(self.solutions_db, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存解决方案库失败: {e}")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        message_obj = event.message_obj
        if not message_obj:
            return

        file_comps = []
        for comp in message_obj.message:
            if isinstance(comp, File):
                file_comps.append(comp)
            elif isinstance(comp, Reply) and comp.chain:
                for replied_comp in comp.chain:
                    if isinstance(replied_comp, File):
                        file_comps.append(replied_comp)

        if file_comps:
            session_id = event.unified_msg_origin
            self._recent_files[session_id] = file_comps[0]

        for file_comp in file_comps:
            file_name = file_comp.name or ""
            zip_pattern = r"错误报告-2026-\d{1,2}-\d{1,2}_\d{2}\.\d{2}\.\d{2}\.zip"
            if file_name.endswith(".zip"):
                if re.match(zip_pattern, file_name):
                    yield event.plain_result(
                        "检测到 PCL 错误报告压缩包。\n"
                        "请引用该文件并发送 /mc_check 开始分析。"
                    )
                    return
                else:
                    yield event.plain_result(
                        "压缩包命名格式不正确，仅接受 PCL/PCLCE 导出的错误报告。\n"
                        "请使用 PCL 或 PCLCE 的「导出错误报告」功能，"
                        "将生成的压缩包发送给我（文件名格式：错误报告-2026-5-31_18.30.06.zip）。"
                    )
                    return

    @filter.command("mc_help")
    async def mc_help(self, event: AstrMessageEvent):
        yield event.plain_result(
            "MC 错误报告分析插件使用说明：\n"
            "1. 上传错误报告：发送 PCL/PCLCE 导出的「错误报告-2026-日期.zip」\n"
            "2. 确认分析：引用该文件并发送 /mc_check\n"
            "3. 手动查询：/mc_check <错误信息>\n"
            "4. 添加方案：/mc_add_solution <错误关键词> <解决方案>\n"
            "5. 查看帮助：/mc_help"
        )

    @filter.command("mc_check")
    async def mc_check(self, event: AstrMessageEvent, error_text: str = ""):
        # 先检查消息中是否有引用的文件（包括回复/引用消息中的文件）
        file_comp = None
        message_obj = event.message_obj
        if message_obj:
            for comp in message_obj.message:
                if isinstance(comp, Reply) and comp.chain:
                    for replied_comp in comp.chain:
                        if isinstance(replied_comp, File):
                            file_comp = replied_comp
                            break
                    if file_comp:
                        break
                if isinstance(comp, File):
                    file_comp = comp
                    break

        # 如果引用中未获取到文件，降级为自动使用最近的文件
        if not file_comp:
            session_id = event.unified_msg_origin
            file_comp = self._recent_files.get(session_id)
            if file_comp:
                yield event.plain_result("未检测到引用的文件，自动使用最近上传的文件...")

        if file_comp:
            async for result in self._handle_error_report(event, file_comp):
                yield result
            return

        if not error_text or error_text.strip() == "":
            yield event.plain_result(
                "用法：\n"
                "1. 引用错误报告压缩包并发送 /mc_check 进行分析\n"
                "2. 或发送 /mc_check <错误信息> 手动查询"
            )
            return

        solution = self._search_local_solutions(error_text)
        if solution:
            yield event.plain_result(f"本地匹配到解决方案：\n{solution}")
        else:
            ai_result = await self._ask_ai_with_context(event, error_text)
            max_display = self._cfg("ai_result_max_chars", 2000)

            error_key = self._extract_error_key(error_text)
            save_cat = self._cfg("auto_save_category", "AI生成")
            if error_key and not self._get_solution(error_key):
                self._set_solution(error_key, ai_result, category=save_cat)
                yield event.plain_result(f"AI 分析结果：\n{ai_result[:max_display]}\n\n（已自动保存到本地知识库）")
            else:
                yield event.plain_result(f"AI 分析结果：\n{ai_result[:max_display]}")

    @filter.command("mc_add_solution")
    async def mc_add_solution(self, event: AstrMessageEvent, error_keyword: str, solution_text: str):
        if not error_keyword or not solution_text:
            yield event.plain_result("用法：/mc_add_solution <错误关键词> <解决方案>")
            return

        self._set_solution(error_keyword.strip(), solution_text.strip(), "用户添加")
        yield event.plain_result(f"已添加解决方案：{error_keyword}")

    async def _handle_error_report(self, event: AstrMessageEvent, file_comp: File):
        yield event.plain_result("正在下载并分析错误报告...")

        file_url = getattr(file_comp, "url", None) or getattr(file_comp, "file", None)
        if not file_url:
            yield event.plain_result("无法获取文件下载链接，请确认文件已上传成功。")
            return

        plugin_data_path = Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_mc_helper"
        reports_dir = plugin_data_path / "错误报告"
        reports_dir.mkdir(parents=True, exist_ok=True)

        zip_name = file_comp.name or f"错误报告-unknown.zip"
        zip_path = str(reports_dir / zip_name)
        extract_dir = str(reports_dir / Path(zip_name).stem)

        try:
            timeout_sec = self._cfg("download_timeout", 120)
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout_sec)
            ) as session:
                async with session.get(file_url) as resp:
                    if resp.status != 200:
                        yield event.plain_result(f"文件下载失败，HTTP {resp.status}")
                        return
                    with open(zip_path, "wb") as f:
                        f.write(await resp.read())

            os.makedirs(extract_dir, exist_ok=True)

            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(extract_dir)
            except zipfile.BadZipFile:
                yield event.plain_result("压缩包损坏，无法解压。请检查文件。")
                return

            error_logs = self._collect_logs(extract_dir)
            if not error_logs:
                yield event.plain_result("压缩包中未找到日志文件。")
                return

            local_solution = self._search_local_solutions(error_logs)
            if local_solution:
                yield event.plain_result(f"✅ 本地匹配到解决方案：\n{local_solution}")
                return

            latest_log = self._collect_latest_log(extract_dir)
            max_bytes = self._cfg("latest_log_max_bytes", 2_000_000)
            fallback_chars = self._cfg("ai_source_fallback_chars", 100_000)
            if latest_log and len(latest_log) > 200:
                ai_source = latest_log[:max_bytes]
            else:
                ai_source = error_logs[:fallback_chars]

            ai_result = await self._ask_ai_with_context(event, ai_source)
            max_display = self._cfg("ai_result_max_chars", 2000)

            error_key = self._extract_error_key(error_logs)
            save_cat = self._cfg("auto_save_category", "AI生成")
            if error_key and not self._get_solution(error_key):
                self._set_solution(error_key, ai_result, category=save_cat)
                yield event.plain_result(f"AI 分析结果：\n{ai_result[:max_display]}\n\n（已自动保存到本地知识库）")
            else:
                yield event.plain_result(f"AI 分析结果：\n{ai_result[:max_display]}")

        except Exception as e:
            logger.error(f"处理错误报告时异常: {e}")
            yield event.plain_result(f"处理过程中出现错误：{str(e)}")

    def _collect_logs(self, extract_dir: str) -> str:
        logs = []
        for root, _, files in os.walk(extract_dir):
            for f in files:
                if f.endswith((".log", ".txt", ".crash", ".json")):
                    file_path = os.path.join(root, f)
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as lf:
                            content = lf.read()
                            if content.strip():
                                logs.append(f"=== {f} ===\n{content}\n")
                    except Exception as e:
                        logger.error(f"读取文件 {f} 失败: {e}")

        crash_report_dir = os.path.join(extract_dir, "crash-reports")
        if os.path.isdir(crash_report_dir):
            for root, _, files in os.walk(crash_report_dir):
                for f in files:
                    file_path = os.path.join(root, f)
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as lf:
                            content = lf.read()
                            if content.strip():
                                logs.append(f"=== crash-reports/{f} ===\n{content}\n")
                    except Exception as e:
                        logger.error(f"读取崩溃报告 {f} 失败: {e}")

        logs_dir = os.path.join(extract_dir, "logs")
        if os.path.isdir(logs_dir):
            for root, _, files in os.walk(logs_dir):
                for f in files:
                    file_path = os.path.join(root, f)
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as lf:
                            content = lf.read()
                            if content.strip():
                                logs.append(f"=== logs/{f} ===\n{content}\n")
                    except Exception as e:
                        logger.error(f"读取日志 {f} 失败: {e}")

        return "\n".join(logs)

    def _collect_latest_log(self, extract_dir: str) -> str:
        logs_dir = os.path.join(extract_dir, "logs")
        latest_log_path = os.path.join(logs_dir, "latest.log")
        if os.path.isfile(latest_log_path):
            try:
                with open(latest_log_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
            except Exception as e:
                logger.error(f"读取 latest.log 失败: {e}")
        for root, _, files in os.walk(extract_dir):
            for f in files:
                if f == "latest.log":
                    file_path = os.path.join(root, f)
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as lf:
                            return lf.read()
                    except Exception as e:
                        logger.error(f"读取 {f} 失败: {e}")
                        return ""
        return ""

    def _search_local_solutions(self, error_text: str) -> Optional[str]:
        for category, entries in self.solutions_db.items():
            for pattern, entry in entries.items():
                solution = entry["solution"] if isinstance(entry, dict) else entry
                if re.search(re.escape(pattern), error_text, re.IGNORECASE):
                    return solution

        exit_code_match = re.search(r"Exit Code[:\s]*(-?\d+)", error_text)
        if exit_code_match:
            ec = exit_code_match.group(1)
            for category, entries in self.solutions_db.items():
                for pattern, entry in entries.items():
                    solution = entry["solution"] if isinstance(entry, dict) else entry
                    if f"Exit Code {ec}" in pattern:
                        return solution

        return None

    def _extract_error_key(self, error_text: str) -> Optional[str]:
        match = re.search(
            r"(?:Caused by:\s*)?(java\.\w+(?:\.\w+)+Error|java\.\w+(?:\.\w+)+Exception"
            r"|Exit Code[:\s]*-?\d+|Couldn't\s+\w+|Failed to \w+"
            r"|Connection \w+|Internal Exception|Missing \w+)",
            error_text,
        )
        if match:
            return match.group(1).strip()

        for line in error_text.split("\n"):
            line = line.strip()
            if line.startswith("java.") or "Exception" in line or "Error" in line:
                words = line.split()[:5]
                key = " ".join(words)
                if len(key) > 10:
                    return key

        return None

    async def _ask_ai_with_context(self, event: AstrMessageEvent, error_text: str) -> str:
        try:
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo)
            if not provider_id:
                return "无法获取 AI 模型，请确认已在 WebUI 中配置了 LLM 提供商。"

            prompt = (
                "你是一个专业的 Minecraft 技术支持专家。请分析以下 latest.log 中的错误信息并给出详细的解决方案。\n\n"
                "请按以下格式回复：\n"
                "【错误分析】简要说明错误原因\n"
                "【解决方案】分步骤给出解决建议（按推荐程度排序）\n"
                "【预防建议】如何避免类似问题\n\n"
                f"错误信息（latest.log）：\n{error_text}"
            )

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            return llm_resp.completion_text or "AI 未能生成有效的解决方案。"

        except Exception as e:
            logger.error(f"AI 分析调用失败: {e}")
            return f"AI 分析调用失败：{str(e)}\n\n建议手动搜索错误信息中的关键词获取解决方案。"

    async def terminate(self):
        logger.info("MC Helper 插件已卸载")
