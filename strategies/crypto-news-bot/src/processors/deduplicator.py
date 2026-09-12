import hashlib
import json

from ..models import NewsItem


def generate_news_id(news: NewsItem) -> str:
    link = (news.link or "").strip()
    identity = ["link", link] if link else ["title-source", news.title.strip(), news.source.strip()]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
