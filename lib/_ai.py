"""AI integration module."""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context

from ._analyzer import extract_report_details


async def ask_ai(context: Context, event: AstrMessageEvent, error_text: str) -> str:
    try:
        pid = await context.get_current_chat_provider_id(event.unified_msg_origin)
        if not pid:
            return "无法获取 AI 模型，请确认已在 WebUI 中配置了 LLM 提供商。"

        details = extract_report_details(error_text)
        ctx = ""
        if details:
            ctx = "从日志中提取的关键信息：\n" + "\n".join(details) + "\n\n"

        prompt = (
            "你是一个专业的 Minecraft 技术支持专家。"
            "请分析以下 latest.log 中的错误信息并给出详细的解决方案。\n\n"
            "请使用 Markdown 格式回复，按以下结构：\n"
            "## 错误分析\n简要说明错误原因\n\n"
            "## 解决方案\n"
            "分步骤给出解决建议（按推荐程度排序），引用关键信息如坐标、文件路径、模组名称等\n\n"
            "## 预防建议\n如何避免类似问题\n\n"
            f"{ctx}错误信息（latest.log）：\n{error_text}"
        )

        resp = await context.llm_generate(chat_provider_id=pid, prompt=prompt)
        return resp.completion_text or "AI 未能生成有效的解决方案。"
    except Exception as e:
        logger.error(f"AI 分析调用失败: {e}")
        return f"AI 分析调用失败：{str(e)}\n\n建议手动搜索错误信息中的关键词获取解决方案。"
