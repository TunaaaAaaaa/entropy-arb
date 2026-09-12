import logging
from urllib.parse import urljoin, urlsplit

import feedparser
import requests

from .base import BaseFetcher
from ..models import NewsItem
from ..utils.text import plain_text

logger = logging.getLogger(__name__)


class RSSFetcher(BaseFetcher):
    def __init__(self, sources, session=None):
        self.sources = sources
        self.http = session or requests
        self.last_errors = 0

    def fetch(self) -> list[NewsItem]:
        news = []
        self.last_errors = 0
        for source in self.sources:
            if not source.get("enabled", True):
                continue
            name = source.get("name", "RSS")
            try:
                response = self.http.get(source["url"], timeout=10, headers={
                    "User-Agent": "crypto-news-bot/0.1 RSS reader",
                    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
                })
                response.raise_for_status()
                parsed = feedparser.parse(response.content)
                if not parsed.version:
                    raise ValueError("Response is not RSS or Atom")
                if parsed.bozo:
                    logger.warning("RSS %s 格式不规范，继续处理可解析条目", name)
                count = 0
                for entry in parsed.entries:
                    try:
                        title = plain_text(entry.get("title", ""))
                        link = urljoin(source["url"], (entry.get("link") or "").strip()) if entry.get("link") else ""
                        if link and urlsplit(link).scheme not in ("http", "https"):
                            link = ""
                        if not title and not link:
                            logger.warning("RSS %s 跳过同时缺少标题和链接的条目", name)
                            continue
                        raw = "\n".join(part.get("value", "") for part in entry.get("content", []))
                        news.append(NewsItem(
                            title=title or "（无标题）", link=link, source=name,
                            published_time=entry.get("published") or entry.get("updated"),
                            summary=plain_text(entry.get("summary", "")) or None,
                            raw_content=plain_text(raw) or None,
                        ))
                        count += 1
                    except Exception as exc:
                        logger.error("RSS %s 单条解析失败（%s），继续后续条目", name, type(exc).__name__)
                logger.info("RSS %s：解析 %d 条新闻", name, count)
            except Exception as exc:
                self.last_errors += 1
                logger.error("RSS %s 抓取失败（%s），继续其他来源", name, type(exc).__name__)
        return news
