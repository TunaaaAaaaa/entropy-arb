from ..models import NewsItem
from ..utils.text import plain_text, shorten


def format_message(news: NewsItem, priority: str) -> str:
    label = {"P0": "🚨 [P0 高优先级]", "P1": "📰 [P1 中优先级]"}.get(priority, f"[{priority}]")
    return "\n".join([
        f"{label} {shorten(plain_text(news.title), 300)}", "",
        f"摘要：{shorten(plain_text(news.summary) or '暂无摘要', 800)}",
        f"来源：{shorten(plain_text(news.source) or '未知来源', 100)}",
        f"时间：{shorten(plain_text(news.published_time) or '未知时间', 100)}",
        f"链接：{shorten(news.link or '暂无链接', 2048)}",
    ])
