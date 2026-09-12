from dataclasses import dataclass
from typing import Optional


@dataclass
class NewsItem:
    title: str
    link: str
    source: str
    published_time: Optional[str] = None
    summary: Optional[str] = None
    raw_content: Optional[str] = None
    source_type: str = "rss"
