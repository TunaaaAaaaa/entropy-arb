import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from ..models import NewsItem


class SQLiteStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pushed_news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_id TEXT NOT NULL UNIQUE,
                    title TEXT, link TEXT, source TEXT, priority TEXT,
                    pushed_at TEXT NOT NULL
                )
            """)
            has_deliveries = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='news_deliveries'").fetchone()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS news_deliveries (
                    news_id TEXT NOT NULL,
                    destination_id TEXT NOT NULL,
                    pushed_at TEXT NOT NULL,
                    PRIMARY KEY (news_id, destination_id)
                )
            """)
            if not has_deliveries:
                # V0.1 only had Feishu. Preserve that history without crediting WeCom.
                conn.execute("INSERT INTO news_deliveries SELECT news_id, 'feishu:legacy', pushed_at FROM pushed_news")

    def _connect(self):
        # Scheduler callbacks may use another thread; no connection crosses threads.
        return sqlite3.connect(self.path, timeout=10)

    def has_news(self, news_id: str) -> bool:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT 1 FROM pushed_news WHERE news_id = ?", (news_id,)).fetchone() is not None

    def mark_pushed(self, news_id: str, news: NewsItem, priority: str) -> bool:
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute("""
                INSERT INTO pushed_news (news_id, title, link, source, priority, pushed_at)
                VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(news_id) DO NOTHING
            """, (news_id, news.title, news.link, news.source, priority, datetime.now(timezone.utc).isoformat()))
            return cursor.rowcount == 1

    def count(self) -> int:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM pushed_news").fetchone()[0]

    def bind_legacy_feishu(self, destination_id):
        with closing(self._connect()) as conn, conn:
            conn.execute("""INSERT OR IGNORE INTO news_deliveries
                SELECT news_id, ?, pushed_at FROM news_deliveries WHERE destination_id='feishu:legacy'""", (destination_id,))
            conn.execute("DELETE FROM news_deliveries WHERE destination_id='feishu:legacy'")

    def has_delivery(self, news_id, destination_id):
        with closing(self._connect()) as conn:
            return conn.execute("SELECT 1 FROM news_deliveries WHERE news_id=? AND destination_id=?", (news_id, destination_id)).fetchone() is not None

    def mark_delivery(self, news_id, destination_id):
        with closing(self._connect()) as conn, conn:
            conn.execute("INSERT OR IGNORE INTO news_deliveries VALUES (?, ?, ?)",
                         (news_id, destination_id, datetime.now(timezone.utc).isoformat()))
