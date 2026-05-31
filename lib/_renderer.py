"""Markdown 转 HTML/图片渲染，用于发送格式化回复"""

import html

try:
    import markdown as _md_lib
    _HAS_MD = True
except ImportError:
    _md_lib = None
    _HAS_MD = False

_HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  body {
    font-family: -apple-system, "Segoe UI", "Noto Sans SC", "Microsoft YaHei",
                 sans-serif;
    font-size: 15px; line-height: 1.7; color: #1a1a1a;
    padding: 28px 32px; max-width: 720px; margin: 0;
    background: #ffffff;
  }
  h2 { font-size: 20px; color: #1976d2; margin: 16px 0 8px; }
  ul { padding-left: 20px; }
  li { margin: 4px 0; }
  code {
    font-family: "Cascadia Code", "Fira Code", Consolas, monospace;
    font-size: 13px; background: #e8e8e8; padding: 1px 5px;
    border-radius: 3px;
  }
  pre {
    background: #f5f5f5; padding: 12px 16px; border-radius: 6px;
    overflow-x: auto; font-size: 13px;
  }
  hr { border: none; border-top: 1px solid #cccccc; margin: 12px 0; }
  em { color: #666; }
  blockquote {
    border-left: 3px solid #1976d2; margin: 8px 0; padding: 4px 12px;
    background: #f8faff;
  }
  p { margin: 6px 0; }
</style>
</head>
<body>__BODY__</body>
</html>"""


def md_to_html(md_text: str) -> str:
    """将 markdown 文本转换为 HTML 文档，供 astrbot 的 html_render 使用"""
    safe = html.escape(md_text)
    if not _HAS_MD:
        return f"<pre>{safe}</pre>"
    try:
        body = _md_lib.markdown(
            md_text,
            extensions=["extra", "codehilite", "nl2br"],
        )
    except Exception:
        # markdown 解析失败时降级为预格式化文本
        body = f"<pre>{safe}</pre>"
    return _HTML_TMPL.replace("__BODY__", body)
