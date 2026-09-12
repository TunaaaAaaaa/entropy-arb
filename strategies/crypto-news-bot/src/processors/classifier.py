import re

from ..models import NewsItem
from ..utils.text import plain_text


class Classifier:
    def __init__(self, filters):
        self.rules = []
        # Preserve the spec's priority order, including P0 overriding IGNORE.
        for priority, key in (("P0", "high_priority_keywords"), ("P1", "medium_priority_keywords"), ("IGNORE", "ignore_keywords")):
            patterns = []
            for keyword in filters.get(key, []):
                keyword = keyword.strip()
                pattern = re.escape(keyword)
                # SEC must not match "second", and AMA must not match "drama".
                if keyword[0].isascii() and keyword[0].isalnum():
                    pattern = r"(?<![a-zA-Z0-9_])" + pattern
                if keyword[-1].isascii() and keyword[-1].isalnum():
                    pattern += r"(?![a-zA-Z0-9_])"
                patterns.append(re.compile(pattern, re.IGNORECASE))
            self.rules.append((priority, patterns))

    def classify(self, news: NewsItem) -> str:
        text = " ".join(plain_text(field) for field in (news.title, news.summary, news.raw_content))
        for priority, patterns in self.rules:
            if any(pattern.search(text) for pattern in patterns):
                return priority
        return "P2"
