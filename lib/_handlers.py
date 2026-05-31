"""Command and message handlers."""

import random
import re
import shutil
import time
import zipfile
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import File, Reply

from ._utils import FAIL_PREFIXES, MAX_RECENT_FILES, RECENT_FILES_KEEP
from ._analyzer import extract_report_details, enrich_solution, search_local_solutions, extract_error_key
from ._security import download_zip, scan_zip, extract_safe_files, RateLimiter
from ._file_utils import collect_logs, collect_latest_log
from ._renderer import md_to_html
from ._cme import analyze_cme_log, generate_cme_guide
from ._duplicate_mods import check_duplicate_mods

_RE_ZIP_NAME = re.compile(r"错误报告-(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}-\d{1,2}-\d{4})_\d{1,2}\.\d{2}\.\d{2}\.zip")
_CLEANUP_RATIO = 0.25


class Handlers:
    def __init__(self, plugin):
        self.p = plugin
        self.rate_limiter = RateLimiter()

    # ── helpers ──

    def _ai_failed(self, result: str) -> bool:
        return not result or result.strip() == "" or result.startswith(FAIL_PREFIXES)

    def _enrich(self, text: str, source: str) -> str:
        details = extract_report_details(source)
        dup = check_duplicate_mods(self.p.dup_data, source)
        result = enrich_solution(text, details)
        return f"{dup}\n\n{result}" if dup else result

    async def _send_img(self, event, md: str):
        html = md_to_html(md)
        url = await self.p.context.html_render(html, {}, return_url=True)
        yield event.image_result(url)

    def _cfg(self, key, default):
        return self.p._cfg(key, default)

    # ── on_message ──

    async def on_message(self, event: AstrMessageEvent):
        if not self.p._is_allowed(event) or self.p.blacklist.is_blacklisted(event.unified_msg_origin):
            return
        msg = event.message_obj
        if not msg:
            return

        fcs = []
        for c in msg.message:
            if isinstance(c, File):
                fcs.append(c)
            elif isinstance(c, Reply) and c.chain:
                for rc in c.chain:
                    if isinstance(rc, File):
                        fcs.append(rc)

        if fcs:
            sid = event.unified_msg_origin
            self.p.recent.pop(sid, None)
            self.p.recent[sid] = fcs[0]
            if len(self.p.recent) > MAX_RECENT_FILES:
                for k in list(self.p.recent)[:-RECENT_FILES_KEEP]:
                    del self.p.recent[k]

        for fc in fcs:
            fn = fc.name or ""
            if fn.endswith(".zip"):
                if _RE_ZIP_NAME.match(fn):
                    async for r in self._handle_error_report(event, fc):
                        yield r
                else:
                    yield event.plain_result(
                        "压缩包命名格式不正确。\n请使用 PCL 或 PCLCE 的「导出错误报告」功能，将生成的压缩包发送给我。"
                    )
                return

    # ── mc_help ──

    async def mc_help(self, event: AstrMessageEvent):
        if not self.p._is_allowed(event):
            return
        yield event.plain_result(
            "MC 错误报告分析插件使用说明：\n"
            "1. 上传错误报告：直接发送 PCL/PCLCE 导出的错误报告压缩包，自动分析\n"
            "2. 手动查询：/mc_check <错误信息>\n"
            "3. 添加方案：/mc_add_solution <错误关键词> <解决方案>\n"
            "4. 个人配置：/mc_config\n"
            "5. 查看历史：/mc_reports\n"
            "6. 查看帮助：/mc_help"
        )

    # ── mc_check ──

    async def mc_check(self, event: AstrMessageEvent, error_text: str = ""):
        if not self.p._is_allowed(event):
            return
        fc = self._find_file(event)
        if fc:
            async for r in self._handle_error_report(event, fc):
                yield r
            return

        if not error_text or error_text.strip() == "":
            yield event.plain_result(
                "用法：/mc_check <错误信息>\n直接发送错误报告压缩包即可自动分析。\n历史报告查询：/mc_reports"
            )
            return

        if not self.rate_limiter.allow(event.unified_msg_origin):
            yield event.plain_result("请求过于频繁，请稍后再试。")
            return

        ai = await self.p.ask_ai(event, error_text)
        md = self._cfg("ai_result_max_chars", 2000)

        if self._ai_failed(ai):
            sol = search_local_solutions(self.p.solutions, error_text)
            if sol:
                details = extract_report_details(error_text)
                result = enrich_solution(f"**📖 本地匹配到解决方案**\n\n{sol}", details)
                async for r in self._send_img(event, result):
                    yield r
                return
            yield event.plain_result(ai or "无法获取解决方案，请稍后重试。")
            return

        details = extract_report_details(error_text)
        result = enrich_solution(ai[:md], details)
        dup = check_duplicate_mods(self.p.dup_data, error_text)
        if dup:
            result = f"{dup}\n\n{result}"

        ek = extract_error_key(error_text)
        sc = self._cfg("auto_save_category", "AI生成")
        if ek and not self.p.get_solution(ek):
            await self.p.save_solution(ek, ai, sc)
            async for r in self._send_img(event, f"**🤖 AI 分析结果**\n\n{result}\n\n*（已自动保存到本地知识库）*"):
                yield r
        else:
            async for r in self._send_img(event, f"**🤖 AI 分析结果**\n\n{result}"):
                yield r

    # ── mc_add_solution ──

    async def mc_add_solution(self, event: AstrMessageEvent):
        if not self.p._is_allowed(event):
            return
        text = event.message_str.strip()
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            yield event.plain_result(
                "用法：/mc_add_solution <错误关键词> <解决方案>\n例如：/mc_add_solution OutOfMemoryError 请调大内存分配"
            )
            return
        _, ek, sol = parts
        await self.p.save_solution(ek.strip(), sol.strip(), "用户添加")
        yield event.plain_result(f"已添加解决方案：{ek}")

    # ── mc_reports ──

    async def mc_reports(self, event: AstrMessageEvent):
        uid = event.unified_msg_origin
        folder = self.p.reports_path / uid
        if not folder.is_dir():
            yield event.plain_result("暂无历史分析记录。")
            return
        sessions = sorted(
            [d for d in folder.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )[:10]
        if not sessions:
            yield event.plain_result("暂无历史分析记录。")
            return
        result = "**📋 最近的分析报告**\n\n"
        for s in sessions:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(s.stat().st_mtime))
            log_count = len(list((s / "原始log").glob("*"))) if (s / "原始log").is_dir() else 0
            has_analysis = (s / "分析结果.md").is_file()
            flag = "✅" if has_analysis else ""
            result += f"- `{s.name}` {flag} ({log_count} 文件, {ts})\n"
        result += "\n报告保存在 `data/错误报告/<用户>/<时间>/` 目录下，超期自动清理。"
        async for r in self._send_img(event, result):
            yield r

    # ── mc_config ──

    async def mc_config(self, event: AstrMessageEvent, args: str = ""):
        uid = event.unified_msg_origin
        parts = args.strip().split(maxsplit=2)

        if not args or parts[0] == "view":
            exts = self.p.get_user_cfg(uid, "save_exts", None)
            anl = self.p.get_user_cfg(uid, "save_analysis", None)
            result = "**⚙️ 个人配置**\n\n"
            result += f"- 保存原始文件类型: `{exts or '.log/.txt/.json'}`\n"
            result += f"- 保存分析结果: `{'开启' if anl or anl is None else '关闭'}`\n"
            result += "\n**修改方法：**\n"
            result += "`/mc_config save_exts .log,.txt`  — 设置保存的文件类型\n"
            result += "`/mc_config save_analysis on`  — 开启保存分析结果\n"
            result += "`/mc_config save_analysis off` — 关闭保存分析结果\n"
            result += "`/mc_config view` — 查看当前配置\n"
            async for r in self._send_img(event, result):
                yield r
            return

        if len(parts) < 2:
            yield event.plain_result("用法：/mc_config <键> <值>\n/mc_config view 查看当前配置")
            return

        key, val = parts[1], parts[2] if len(parts) > 2 else ""
        if key == "save_exts":
            exts = [e.strip() for e in val.split(",") if e.strip()]
            self.p.set_user_cfg(uid, "save_exts", exts)
            yield event.plain_result(f"已设置保存文件类型: {exts}")
        elif key == "save_analysis":
            if val.lower() in ("on", "true", "1", "yes"):
                self.p.set_user_cfg(uid, "save_analysis", True)
                yield event.plain_result("已开启保存分析结果")
            elif val.lower() in ("off", "false", "0", "no"):
                self.p.set_user_cfg(uid, "save_analysis", False)
                yield event.plain_result("已关闭保存分析结果")
            else:
                yield event.plain_result("值应为 on/off")
        else:
            yield event.plain_result(f"未知配置项: {key}")

    # ── file lookup ──

    def _find_file(self, event) -> File | None:
        msg = event.message_obj
        if msg:
            for c in msg.message:
                if isinstance(c, Reply) and c.chain:
                    for rc in c.chain:
                        if isinstance(rc, File):
                            return rc
                if isinstance(c, File):
                    return c
        fc = self.p.recent.get(event.unified_msg_origin)
        if fc:
            return fc
        return None

    # ── error report pipeline ──

    async def _handle_error_report(self, event, fc):
        uid = event.unified_msg_origin
        if self.p.blacklist.is_blacklisted(uid):
            yield event.plain_result("你已被限制使用此功能。")
            return

        if not self.rate_limiter.allow(uid):
            yield event.plain_result("请求过于频繁，请稍后再试。")
            return

        yield event.plain_result("正在下载并分析错误报告...")

        url = getattr(fc, "url", None) or getattr(fc, "file", None)
        if not url:
            yield event.plain_result("无法获取文件下载链接。")
            return

        rd = self.p.reports_path
        zname = fc.name or "unknown.zip"
        zpath = rd / zname
        edir = rd / Path(zname).stem

        try:
            await download_zip(url, zpath, self._cfg("download_timeout", 120))
            bl = scan_zip(zpath)
            if bl:
                if bl == ["__too_many_files__"]:
                    yield event.plain_result("压缩包内文件过多，已拒绝。")
                else:
                    logger.warning(f"黑名单文件: {bl}")
                    self.p.blacklist.record_malicious(uid, self._cfg("max_malicious_uploads", 3))
                    yield event.plain_result("压缩包包含不允许的文件类型，已拒绝处理。")
                shutil.rmtree(edir, ignore_errors=True)
                return

            edir.mkdir(parents=True, exist_ok=True)
            if extract_safe_files(zpath, edir) == 0:
                yield event.plain_result("压缩包中未找到可分析的日志文件。")
                shutil.rmtree(edir, ignore_errors=True)
                return
            if zpath.exists():
                zpath.unlink()
        except (zipfile.BadZipFile, ValueError, ConnectionError):
            yield event.plain_result("压缩包无效或无法访问，请检查文件来源。")
            return
        except Exception as e:
            logger.error(f"解压异常: {e}")
            yield event.plain_result("解压失败，请稍后重试。")
            return
        finally:
            if zpath.exists():
                zpath.unlink()

        logs = collect_logs(edir)
        latest = collect_latest_log(edir)
        mb = self._cfg("latest_log_max_bytes", 2_000_000)
        fb = self._cfg("ai_source_fallback_chars", 100_000)
        source = latest[:mb] if latest and len(latest) > 200 else logs[:fb]

        ai = await self.p.ask_ai(event, source)
        md = self._cfg("ai_result_max_chars", 2000)

        if self._ai_failed(ai):
            local = search_local_solutions(self.p.solutions, logs)
            if local:
                details = extract_report_details(logs)
                result = enrich_solution(f"**✅ 本地匹配到解决方案**\n\n{local}", details)
                dup = check_duplicate_mods(self.p.dup_data, logs)
                if dup:
                    result = f"{dup}\n\n{result}"
                async for r in self._send_img(event, result):
                    yield r
                return
            yield event.plain_result(ai or "无法获取解决方案。")
            return

        details = extract_report_details(source)
        result = enrich_solution(ai[:md], details)
        dup = check_duplicate_mods(self.p.dup_data, source)
        if dup:
            result = f"{dup}\n\n{result}"

        if "ConcurrentModificationException" in logs:
            cme_log = edir / "CMESuckMyDuck.log"
            if cme_log.is_file():
                cme = analyze_cme_log(cme_log)
                if cme:
                    result += "\n\n---\n" + cme
            else:
                guide = generate_cme_guide(logs)
                if guide:
                    result += "\n\n---\n" + guide

        ek = extract_error_key(logs)
        sc = self._cfg("auto_save_category", "AI生成")
        suffix = "\n\n*（已自动保存到本地知识库）*"
        if ek and not self.p.get_solution(ek):
            await self.p.save_solution(ek, ai, sc)
            async for r in self._send_img(event, f"**🤖 AI 分析结果**\n\n{result}{suffix}"):
                yield r
        else:
            async for r in self._send_img(event, f"**🤖 AI 分析结果**\n\n{result}"):
                yield r

        self._save_report(uid, edir, result)
        shutil.rmtree(edir, ignore_errors=True)

    # ── report persistence ──

    def _save_report(self, uid: str, extract_dir: Path, analysis: str):
        ts = time.strftime("%Y%m%d_%H%M%S")
        dst = self.p.reports_path / uid / ts
        dst.mkdir(parents=True, exist_ok=True)

        exts = self.p.get_user_cfg(uid, "save_exts", [".log", ".txt", ".json"])
        root = extract_dir.resolve()
        log_dir = dst / "原始log"
        log_dir.mkdir(parents=True, exist_ok=True)
        for f in extract_dir.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in exts:
                continue
            if f.is_symlink():
                try:
                    resolved = f.resolve()
                    if not str(resolved).startswith(str(root)):
                        continue
                except (OSError, RuntimeError):
                    continue
            try:
                c = f.read_text(encoding="utf-8", errors="ignore")
                if not c.strip():
                    continue
                (log_dir / f.name).write_text(c, encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                logger.debug(f"保存日志失败: {e}")

        if self.p.get_user_cfg(uid, "save_analysis", True):
            (dst / "分析结果.md").write_text(analysis, encoding="utf-8")

        if random.random() < _CLEANUP_RATIO:
            self._cleanup_old_reports(uid)

    def _cleanup_old_reports(self, uid: str):
        try:
            folder = self.p.reports_path / uid
            if not folder.is_dir():
                return
            days = self._cfg("max_report_age_days", 7)
            now = time.time()
            cutoff = now - days * 86400
            for d in folder.iterdir():
                if d.is_dir():
                    try:
                        st = d.stat()
                        if st.st_mtime < cutoff:
                            shutil.rmtree(d, ignore_errors=True)
                            logger.info(f"清理过期报告: {d.name}")
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"清理旧报告失败: {e}")
