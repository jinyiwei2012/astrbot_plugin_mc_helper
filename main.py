import asyncio
import copy
import json
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Optional

import aiohttp

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import File, Reply
from astrbot.api.star import Context, Star, StarTools


# Module-level compiled regex patterns
_RE_JAR_PATH = re.compile(
    r"(?:^|[\s\\/])mods[\\/]([\w\-+]+(?:mc[\w\-+.]+)?\d[\w.+]*\.jar)",
    re.IGNORECASE,
)
_RE_JAR_NAME = re.compile(r"[\w\-+]+(?:mc[\w\-+.]+)?\d[\w.+]*\.jar", re.IGNORECASE)
_RE_MOD_FILE = re.compile(
    r"(?:Mod|Mod File|File):\s*([\w\-+]+(?:mc[\w\-+.]+)?\d[\w.+]*\.jar)",
    re.IGNORECASE,
)
_RE_DUP_SECTION = re.compile(
    r"Duplicate\s*Mod[s]?[:\s]*\n((?:.{0,300}\n?){0,15})",
    re.IGNORECASE,
)
_RE_EXIT_CODE = re.compile(r"Exit Code[:\s]*(-?\d+)")
_RE_STACK = re.compile(r"at\s+([\w.]+)\(([^:]+:\d+)\)")
_RE_COORDS = re.compile(r"(?:Tile Entity at|Block at|Position)\s*\[?(-?\d+)[,; ]\s*(-?\d+)[,; ]\s*(-?\d+)\]?")
_RE_MEMORY = re.compile(r"(\d+)\s*(MB|GB|MiB|GiB)", re.IGNORECASE)
_RE_SERVER = re.compile(
    r"(?:^|\n)(?:Server|Server IP|Host|Server Address)[:\s]*([\w.\-]+(?::\d+)?)",
    re.IGNORECASE,
)
_RE_PATH = re.compile(
    r"(?:\.minecraft[\\/](?!libraries)[\w\\/.\-]+(?:\.log|\.txt|\.json|\.jar|\.zip|\.mca))",
    re.IGNORECASE,
)
_RE_JAVA = re.compile(r"Java\s*(?:Version|VM|Runtime)[:\s]*([\d.]+)", re.IGNORECASE)
_RE_OS = re.compile(r"Operating\s+System[:\s]*([^\n]+)", re.IGNORECASE)
_RE_MOD_ID = re.compile(r"([a-z_]+:[a-z_]+)")
_RE_EXCEPTION = re.compile(r"(?:Caused by|Description)[:\s]*([^\n]+)")
_RE_ERROR_CLS = re.compile(
    r"(java\.\w+(?:\.\w+)+Error|java\.\w+(?:\.\w+)+Exception|"
    r"IllegalStateException|NullPointerException|"
    r"ConcurrentModificationException)[:\s]*([^\n]*)"
)
_SKIP_STACK = (
    "cpw.mods.modlauncher",
    "cpw.mods.bootstraplauncher",
    "java.lang",
    "jdk.internal",
    "sun.reflect",
    "net.minecraft.launchwrapper",
    "org.spongepowered.asm",
    "net.minecraftforge.fml.loading",
)
_SKIP_MOD_ID = {
    "minecraft",
    "java",
    "net",
    "com",
    "org",
    "cpw",
    "it",
    "de",
    "fr",
    "io",
    "pl",
}

try:
    import markdown as _md_lib

    _HAS_MD = True
except ImportError:
    _md_lib = None
    _HAS_MD = False


class McHelperPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config

        self.plugin_data_path = StarTools.get_data_dir("astrbot_plugin_mc_helper")
        self.plugin_data_path.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

        solutions_src = Path(__file__).parent / "data" / "solutions.json"
        self.solutions_db_path = self.plugin_data_path / "solutions.json"

        if not self.solutions_db_path.exists() and solutions_src.exists():
            shutil.copy2(solutions_src, self.solutions_db_path)

        self.solutions_db = self._load_solutions_db()
        self.duplicate_mods_data = self._load_duplicate_mods()
        self._recent_files: dict[str, File] = {}
        logger.info(
            f"MC Helper 插件已加载，本地方案库共 {self._count_solutions()} 条，配置项 {len(config) if config else 0} 个"
        )

    def _cfg(self, key: str, default):
        if self.config and key in self.config:
            return self.config[key]
        return default

    def _is_allowed_group(self, event: AstrMessageEvent) -> bool:
        whitelist = self._cfg("whitelist_groups", [])
        if not whitelist:
            return True
        group_id = event.get_group_id()
        return group_id in whitelist

    def _load_solutions_db(self) -> dict:
        if self.solutions_db_path.exists():
            try:
                with open(self.solutions_db_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载解决方案库失败: {e}")
        return {}

    def _load_duplicate_mods(self) -> dict:
        path = Path(__file__).parent / "data" / "duplicate_mods.json"
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"加载重复模组对照表失败: {e}")
        return {"mod_groups": []}

    def _check_duplicate_mods(self, error_text: str) -> str | None:
        found_jars = _RE_JAR_NAME.findall(error_text)
        found_paths = _RE_JAR_PATH.findall(error_text)
        dup_section = _RE_DUP_SECTION.search(error_text)
        if dup_section and not found_paths:
            section = dup_section.group(1)
            found_paths = _RE_JAR_PATH.findall(section)
            if not found_paths:
                found_paths = _RE_JAR_NAME.findall(section)

        for group in self.duplicate_mods_data.get("mod_groups", []):
            current = group.get("current", "")
            aliases = group.get("aliases", [])
            all_names = [s.lower() for s in ([current] + aliases)]
            matched_jars = []
            matched_paths = []

            for j in found_jars:
                j_lower = j.lower()
                for name in all_names:
                    if name.lower() in j_lower:
                        matched_jars.append(j)
                        break

            for p in found_paths:
                p_lower = p.lower()
                for name in all_names:
                    if name.lower() in p_lower:
                        matched_paths.append(p)
                        break

            found_by_name = [name for name in ([current] + aliases) if name.lower() in error_text.lower()]

            if len(set(matched_jars)) >= 2 or len(set(matched_paths)) >= 2:
                result = f"**⚠️ 检测到同一类模组出现多个：{', '.join(found_by_name)}**\n\n"
                result += f"{group.get('note', '')}\n"
                if matched_paths:
                    result += "\n**检测到的冲突文件：**\n"
                    for p in set(matched_paths):
                        result += f"- `{p}`\n"
                elif matched_jars:
                    unique_jars = list(set(matched_jars))[:5]
                    result += "\n**检测到的冲突文件：**\n"
                    for j in unique_jars:
                        result += f"- `{j}`\n"
                result += (
                    f"\n**如何清理**\n"
                    f"1. 打开 `.minecraft/mods` 文件夹（PCL 里点「设置」→「模组文件夹」）\n"
                    f"2. 在文件夹里搜索上面列出的文件名，把旧版/别名版删掉\n"
                    f"3. 只保留 `{current}`，删完重启游戏\n\n"
                    f"👉 {group.get('recommendation', '只保留一个')}\n\n"
                    f"**常见文件名示例：**\n"
                )
                examples = group.get("examples", [])
                result += "\n".join(f"- `{e}`" for e in examples[:3])
                return result

            if len(set(found_by_name)) >= 2:
                examples = group.get("examples", [])
                ex = "\n".join(f"- `{e}`" for e in examples[:3])
                return (
                    f"**⚠️ 检测到同一类模组出现多个："
                    f"{', '.join(found_by_name)}**\n\n"
                    f"{group.get('note', '')}\n\n"
                    f"**如何清理**\n"
                    f"1. 打开 `.minecraft/mods` 文件夹（PCL 里点「模组文件夹」就能直达）\n"
                    f"2. 搜索上面提到的文件名，把旧版/别名版删掉，只保留 `{current}`\n"
                    f"3. 删完重启游戏\n\n"
                    f"👉 {group.get('recommendation', '只保留一个')}\n\n"
                    f"**常见文件名示例：**\n{ex}"
                )
        return None

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

    async def _set_solution(self, key: str, solution: str, category: str = "AI生成"):
        async with self._lock:
            old_db = copy.deepcopy(self.solutions_db)
            try:
                if category not in self.solutions_db:
                    self.solutions_db[category] = {}
                self.solutions_db[category][key] = {"solution": solution}
                with open(self.solutions_db_path, "w", encoding="utf-8") as f:
                    json.dump(self.solutions_db, f, ensure_ascii=False, indent=2)
            except Exception as e:
                self.solutions_db = old_db
                logger.error(f"保存解决方案库失败: {e}")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if not self._is_allowed_group(event):
            return
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
            if len(self._recent_files) > 200:
                for k in list(self._recent_files)[:-100]:
                    del self._recent_files[k]

        for file_comp in file_comps:
            file_name = file_comp.name or ""
            zip_pattern = r"错误报告-2026-\d{1,2}-\d{1,2}_\d{2}\.\d{2}\.\d{2}\.zip"
            if file_name.endswith(".zip"):
                if re.match(zip_pattern, file_name):
                    async for result in self._handle_error_report(event, file_comp):
                        yield result
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
        if not self._is_allowed_group(event):
            return
        yield event.plain_result(
            "MC 错误报告分析插件使用说明：\n"
            "1. 上传错误报告：发送 PCL/PCLCE 导出的「错误报告-2026-日期.zip」，自动分析\n"
            "2. 手动查询：/mc_check <错误信息>\n"
            "3. 添加方案：/mc_add_solution <错误关键词> <解决方案>\n"
            "4. 查看帮助：/mc_help"
        )

    @filter.command("mc_check")
    async def mc_check(self, event: AstrMessageEvent, error_text: str = ""):
        if not self._is_allowed_group(event):
            return
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
            yield event.plain_result("用法：/mc_check <错误信息>\n直接发送错误报告压缩包即可自动分析。")
            return

        ai_result = await self._ask_ai_with_context(event, error_text)
        max_display = self._cfg("ai_result_max_chars", 2000)

        fail_prefixes = (
            "无法获取 AI 模型",
            "AI 未能生成有效的解决方案",
            "AI 分析调用失败",
        )
        ai_failed = not ai_result or ai_result.strip() == "" or ai_result.startswith(fail_prefixes)

        if ai_failed:
            solution = self._search_local_solutions(error_text)
            if solution:
                dup_warning = self._check_duplicate_mods(error_text)
                result = self._enrich_solution(f"**📖 本地匹配到解决方案**\n\n{solution}", error_text)
                if dup_warning:
                    result = f"{dup_warning}\n\n{result}"
                async for r in self._send_md_image(event, result):
                    yield r
                return

            yield event.plain_result(ai_result or "无法获取解决方案，请稍后重试。")
            return

        dup_warning = self._check_duplicate_mods(error_text)
        result_text = self._enrich_solution(ai_result[:max_display], error_text)
        if dup_warning:
            result_text = f"{dup_warning}\n\n{result_text}"

        error_key = self._extract_error_key(error_text)
        save_cat = self._cfg("auto_save_category", "AI生成")
        if error_key and not self._get_solution(error_key):
            await self._set_solution(error_key, ai_result, category=save_cat)
            async for r in self._send_md_image(
                event,
                f"**🤖 AI 分析结果**\n\n{result_text}\n\n*（已自动保存到本地知识库）*",
            ):
                yield r
        else:
            async for r in self._send_md_image(event, f"**🤖 AI 分析结果**\n\n{result_text}"):
                yield r

    @filter.command("mc_add_solution")
    async def mc_add_solution(self, event: AstrMessageEvent):
        if not self._is_allowed_group(event):
            return
        text = event.message_str.strip()
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            yield event.plain_result(
                "用法：/mc_add_solution <错误关键词> <解决方案>\n例如：/mc_add_solution OutOfMemoryError 请调大内存分配"
            )
            return
        _, error_keyword, solution_text = parts
        await self._set_solution(error_keyword.strip(), solution_text.strip(), "用户添加")
        yield event.plain_result(f"已添加解决方案：{error_keyword}")

    async def _handle_error_report(self, event: AstrMessageEvent, file_comp: File):
        yield event.plain_result("正在下载并分析错误报告...")

        file_url = getattr(file_comp, "url", None) or getattr(file_comp, "file", None)
        if not file_url:
            yield event.plain_result("无法获取文件下载链接，请确认文件已上传成功。")
            return

        reports_dir = self.plugin_data_path / "错误报告"
        reports_dir.mkdir(parents=True, exist_ok=True)

        zip_name = file_comp.name or "错误报告-unknown.zip"
        zip_path = reports_dir / zip_name
        extract_dir = reports_dir / Path(zip_name).stem

        try:
            timeout_sec = self._cfg("download_timeout", 120)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_sec)) as session:
                async with session.get(file_url) as resp:
                    if resp.status != 200:
                        yield event.plain_result(f"文件下载失败，HTTP {resp.status}")
                        return
                    with open(zip_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(65536):
                            f.write(chunk)

            extract_dir.mkdir(parents=True, exist_ok=True)

            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    infos = zf.infolist()
                    if len(infos) > 1000:
                        yield event.plain_result("压缩包内文件过多（超过 1000 个），已拒绝解压。")
                        shutil.rmtree(extract_dir, ignore_errors=True)
                        return
                    max_extract_size = 50 * 1024 * 1024
                    max_file_size = 10 * 1024 * 1024
                    total_size = 0
                    for info in infos:
                        if info.file_size > max_file_size:
                            yield event.plain_result(f"压缩包内存在单文件过大（{info.filename}），已拒绝解压。")
                            shutil.rmtree(extract_dir, ignore_errors=True)
                            return
                        total_size += info.file_size
                        if total_size > max_extract_size:
                            yield event.plain_result("压缩包解压后总大小超过 50MB，已拒绝解压。")
                            shutil.rmtree(extract_dir, ignore_errors=True)
                            return
                        filename = info.filename
                        if (
                            filename.startswith("/")
                            or "/../" in filename
                            or filename == ".."
                            or filename.startswith("../")
                        ):
                            yield event.plain_result("压缩包包含无效的路径，已拒绝解压。")
                            shutil.rmtree(extract_dir, ignore_errors=True)
                            return
                        target_path = (extract_dir / filename).resolve()
                        if not str(target_path).startswith(str(extract_dir.resolve())):
                            yield event.plain_result("压缩包包含无效的路径，已拒绝解压。")
                            shutil.rmtree(extract_dir, ignore_errors=True)
                            return
                        zf.extract(info, extract_dir)
            except zipfile.BadZipFile:
                yield event.plain_result("压缩包损坏，无法解压。请检查文件。")
                return
            finally:
                if zip_path.exists():
                    zip_path.unlink()

            error_logs = self._collect_logs(extract_dir)
            if not error_logs:
                yield event.plain_result("压缩包中未找到日志文件。")
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

            fail_prefixes = (
                "无法获取 AI 模型",
                "AI 未能生成有效的解决方案",
                "AI 分析调用失败",
            )
            ai_failed = not ai_result or ai_result.strip() == "" or ai_result.startswith(fail_prefixes)

            if ai_failed:
                local_solution = self._search_local_solutions(error_logs)
                if local_solution:
                    dup_warning = self._check_duplicate_mods(error_logs)
                    result = self._enrich_solution(
                        f"**✅ 本地匹配到解决方案**\n\n{local_solution}",
                        error_logs,
                    )
                    if dup_warning:
                        result = f"{dup_warning}\n\n{result}"
                    async for r in self._send_md_image(event, result):
                        yield r
                    return

                yield event.plain_result(ai_result or "无法获取解决方案，请稍后重试。")
                return

            dup_warning = self._check_duplicate_mods(ai_source)
            result_text = self._enrich_solution(ai_result[:max_display], ai_source)
            if dup_warning:
                result_text = f"{dup_warning}\n\n{result_text}"

            error_key = self._extract_error_key(error_logs)
            save_cat = self._cfg("auto_save_category", "AI生成")
            if error_key and not self._get_solution(error_key):
                await self._set_solution(error_key, ai_result, category=save_cat)
                async for r in self._send_md_image(
                    event,
                    f"**🤖 AI 分析结果**\n\n{result_text}\n\n*（已自动保存到本地知识库）*",
                ):
                    yield r
            else:
                async for r in self._send_md_image(event, f"**🤖 AI 分析结果**\n\n{result_text}"):
                    yield r

        except Exception as e:
            logger.error(f"处理错误报告时异常: {e}")
            yield event.plain_result(f"处理过程中出现错误：{str(e)}")
        finally:
            self._cleanup_old_files()

    def _cleanup_old_files(self):
        try:
            reports_dir = self.plugin_data_path / "错误报告"
            if not reports_dir.is_dir():
                return
            max_age_days = self._cfg("max_report_age_days", 7)
            cutoff = time.time() - max_age_days * 86400
            for item in reports_dir.iterdir():
                try:
                    mtime = item.stat().st_mtime
                    if mtime < cutoff:
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                        else:
                            item.unlink(missing_ok=True)
                        logger.info(f"清理旧错误报告文件: {item.name}")
                except Exception as e:
                    logger.debug(f"清理文件 {item.name} 时出错: {e}")
        except Exception as e:
            logger.debug(f"清理旧文件时出错: {e}")

    def _collect_logs(self, extract_dir: Path) -> str:
        logs = []
        for f in extract_dir.rglob("*"):
            if f.is_file() and f.suffix in (".log", ".txt", ".crash", ".json"):
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")
                    if content.strip():
                        logs.append(f"=== {f.name} ===\n{content}\n")
                except Exception as e:
                    logger.error(f"读取文件 {f.name} 失败: {e}")

        crash_report_dir = extract_dir / "crash-reports"
        if crash_report_dir.is_dir():
            for f in crash_report_dir.rglob("*"):
                if f.is_file():
                    try:
                        content = f.read_text(encoding="utf-8", errors="ignore")
                        if content.strip():
                            logs.append(f"=== crash-reports/{f.name} ===\n{content}\n")
                    except Exception as e:
                        logger.error(f"读取崩溃报告 {f.name} 失败: {e}")

        logs_dir = extract_dir / "logs"
        if logs_dir.is_dir():
            for f in logs_dir.rglob("*"):
                if f.is_file():
                    try:
                        content = f.read_text(encoding="utf-8", errors="ignore")
                        if content.strip():
                            logs.append(f"=== logs/{f.name} ===\n{content}\n")
                    except Exception as e:
                        logger.error(f"读取日志 {f.name} 失败: {e}")

        return "\n".join(logs)

    def _collect_latest_log(self, extract_dir: Path) -> str:
        crash_output_path = extract_dir / "游戏崩溃前的输出.txt"
        if crash_output_path.is_file():
            try:
                content = crash_output_path.read_text(encoding="utf-8", errors="ignore")
                if content.strip():
                    return content
            except Exception as e:
                logger.error(f"读取 游戏崩溃前的输出.txt 失败: {e}")

        latest_log_path = extract_dir / "logs" / "latest.log"
        if latest_log_path.is_file():
            try:
                return latest_log_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.error(f"读取 latest.log 失败: {e}")
        for f in extract_dir.rglob("latest.log"):
            if f.is_file():
                try:
                    return f.read_text(encoding="utf-8", errors="ignore")
                except Exception as e:
                    logger.error(f"读取 {f.name} 失败: {e}")
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

    def _extract_report_details(self, error_text: str) -> list[str]:
        details = []

        jar_paths = _RE_JAR_PATH.findall(error_text)
        if jar_paths:
            details.append("涉及文件：" + "、".join(set(jar_paths[:3])))

        mod_names = _RE_MOD_FILE.findall(error_text)
        if mod_names and not jar_paths:
            details.append("涉及模组：" + ", ".join(set(mod_names[:3])))

        mod_ids = set()
        for m in _RE_MOD_ID.findall(error_text):
            parts = m.split(":")
            if parts[0] not in _SKIP_MOD_ID:
                mod_ids.add(m)
        mod_id_list = sorted(mod_ids)[:4]
        if mod_id_list:
            details.append("涉及模组 ID：" + "、".join(mod_id_list))

        dup_section = _RE_DUP_SECTION.search(error_text)
        if dup_section:
            dup_files = _RE_JAR_NAME.findall(dup_section.group(1))
            if dup_files:
                details.append("重复模组：" + "、".join(set(dup_files[:5])))

        exit_code = _RE_EXIT_CODE.search(error_text)
        if exit_code:
            details.append("退出代码：Exit Code " + exit_code.group(1))

        exception = _RE_EXCEPTION.search(error_text)
        if exception:
            msg = exception.group(1).strip()
            if msg and len(msg) < 120:
                details.append("错误信息：{}".format(msg))

        error_keyword = _RE_ERROR_CLS.search(error_text)
        if error_keyword:
            ex_type = error_keyword.group(1).split(".")[-1]
            ex_msg = error_keyword.group(2).strip()[:80] if error_keyword.group(2) else ""
            if ex_msg:
                details.append("异常：{} - {}".format(ex_type, ex_msg))
            else:
                details.append("异常：{}".format(ex_type))

        all_stacks = _RE_STACK.findall(error_text)
        meaningful = [s for s in all_stacks if not s[0].startswith(_SKIP_STACK)]
        if meaningful:
            details.append("异常位置：{} ({})".format(meaningful[0][0], meaningful[0][1]))

        coords = _RE_COORDS.findall(error_text)
        if coords:
            details.append("坐标：({}, {}, {})".format(coords[0][0], coords[0][1], coords[0][2]))

        memory = _RE_MEMORY.findall(error_text)
        if memory:
            details.append("内存：{} {}".format(memory[0][0], memory[0][1]))

        servers = _RE_SERVER.findall(error_text)
        if servers:
            details.append("服务器：{}".format(servers[0]))

        paths = _RE_PATH.findall(error_text)
        if paths:
            details.append("路径：{}".format(paths[0]))

        java_versions = _RE_JAVA.findall(error_text)
        if java_versions:
            details.append("Java 版本：{}".format(java_versions[0]))

        os_info = _RE_OS.findall(error_text)
        if os_info:
            details.append("系统：{}".format(os_info[0].strip()))

        return details

    def _enrich_solution(self, solution: str, error_text: str) -> str:
        details = self._extract_report_details(error_text)

        result = solution + "\n\n---"

        tips = []

        if details:
            for d in details:
                if d.startswith("涉及文件") or d.startswith("涉及模组"):
                    files = d.split("：")[1] if "：" in d else ""
                    tip_parts = []
                    for f in files.replace("、", " ").split():
                        if ".jar" in f.lower():
                            tip_parts.append(f)
                    if tip_parts:
                        tips.append(
                            "打开 .minecraft/mods 文件夹，找到上面对应的文件，"
                            + "、".join(tip_parts[:3])
                            + "。检查是否需要删除旧版或解决冲突。"
                        )

            if d.startswith("坐标"):
                coord = d.split("：")[1] if "：" in d else ""
                tips.append(
                    f"前往坐标 {coord} 检查。如果是方块实体崩溃，拆掉该位置的方块；"
                    "如果是实体崩溃，用 /kill @e 清除附近的实体。"
                )

            if d.startswith("内存"):
                val = d.split("：")[1] if "：" in d else ""
                tips.append(
                    f"当前内存分配为 {val}。如果游戏卡顿或内存不足，在 PCL 设置中将内存调大（如 4096MB 或 6144MB）。"
                )

            if d.startswith("Java 版本"):
                ver = d.split("：")[1] if "：" in d else ""
                tips.append(
                    f"当前 Java 版本为 {ver}。如果遇到不兼容错误，"
                    "在 PCL 设置中更换 Java 版本（MC 1.17+ 需要 Java 17 或 21）。"
                )

            if d.startswith("服务器"):
                srv = d.split("：")[1] if "：" in d else ""
                tips.append(f"服务器地址：{srv}。如果是连接问题，检查地址是否正确、服务器是否开启、网络是否正常。")

            if d.startswith("路径") and ".mca" in d:
                tips.append(
                    "发现区块文件(.mca)损坏，用 MCA Selector 打开该文件，找到损坏的区块并删除（游戏会自动重新生成）。"
                )

            if d.startswith("路径") and ".json" in d:
                tips.append("发现配置文件(.json)异常，尝试删除该配置文件（游戏会自动重建默认配置）。")

            if d.startswith("异常位置"):
                try:
                    loc = d.split("：")[1] if "：" in d else ""
                    cls = loc.split("(")[0].strip() if "(" in loc else loc
                    short = cls.split(".")[-1] if "." in cls else cls
                    tips.append(f"错误出现在 {short} 类中。如果该类和模组相关，尝试更新或删除对应的模组。")
                except Exception:
                    pass

            if d.startswith("系统"):
                sys_text = d.split("：")[1] if "：" in d else ""
                if "linux" in sys_text.lower() or "mac" in sys_text.lower():
                    tips.append("你正在使用非 Windows 系统，某些模组可能不兼容。检查模组是否支持你的操作系统。")

            if d.startswith("退出代码"):
                ec = d.split("：")[1] if "：" in d else ""
                tips.append(
                    f"退出代码 {ec}。请对照本地方案库中的 Exit Code 相关条目排查，"
                    "通常与内存、显卡驱动或 Java 配置有关。"
                )

            if d.startswith("重复模组"):
                tips.append(
                    "检测到重复模组！打开 .minecraft/mods 文件夹，搜到上面对应的文件名，只保留一个版本，删除其余。"
                )

        result += "\n\n---"
        if details:
            result += "\n\n**📋 错误详情**"
            for d in details:
                result += "\n- " + d

        if tips:
            result += "\n\n**🔧 定位解决**"
            for t in tips[:5]:
                result += "\n- " + t

        return result

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

            details = self._extract_report_details(error_text)
            context_block = ""
            if details:
                context_block = "从日志中提取的关键信息：\n" + "\n".join(details) + "\n\n"

            prompt = (
                "你是一个专业的 Minecraft 技术支持专家。请分析以下 latest.log 中的错误信息并给出详细的解决方案。\n\n"
                "请使用 Markdown 格式回复，按以下结构：\n"
                "## 错误分析\n"
                "简要说明错误原因\n\n"
                "## 解决方案\n"
                "分步骤给出解决建议（按推荐程度排序），引用关键信息如坐标、文件路径、模组名称等\n\n"
                "## 预防建议\n"
                "如何避免类似问题\n\n"
                f"{context_block}错误信息（latest.log）：\n{error_text}"
            )

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            return llm_resp.completion_text or "AI 未能生成有效的解决方案。"

        except Exception as e:
            logger.error(f"AI 分析调用失败: {e}")
            return f"AI 分析调用失败：{str(e)}\n\n建议手动搜索错误信息中的关键词获取解决方案。"

    def _md_to_html(self, md_text: str) -> str:
        if not _HAS_MD:
            return f"<pre>{md_text}</pre>"
        body = _md_lib.markdown(
            md_text,
            extensions=["extra", "codehilite", "nl2br"],
        )
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  body {{
    font-family: -apple-system, "Segoe UI", "Noto Sans SC", "Microsoft YaHei",
                 sans-serif;
    font-size: 15px; line-height: 1.7; color: #1a1a1a;
    padding: 28px 32px; max-width: 720px; margin: 0;
    background: #ffffff;
  }}
  h2 {{ font-size: 20px; color: #1976d2; margin: 16px 0 8px; }}
  ul {{ padding-left: 20px; }}
  li {{ margin: 4px 0; }}
  code {{
    font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
    font-size: 13px; background: #e8e8e8; padding: 1px 5px;
    border-radius: 3px;
  }}
  pre {{
    background: #f5f5f5; padding: 12px 16px; border-radius: 6px;
    overflow-x: auto; font-size: 13px;
  }}
  hr {{ border: none; border-top: 1px solid #cccccc; margin: 12px 0; }}
  em {{ color: #666; }}
  blockquote {{
    border-left: 3px solid #1976d2; margin: 8px 0; padding: 4px 12px;
    background: #f8faff;
  }}
  p {{ margin: 6px 0; }}
</style>
</head>
<body>{body}</body>
</html>"""

    async def _send_md_image(self, event, md_text: str):
        html = self._md_to_html(md_text)
        url = await self.html_render(html, {}, return_url=True)
        yield event.image_result(url)

    async def terminate(self):
        logger.info("MC Helper 插件已卸载")
