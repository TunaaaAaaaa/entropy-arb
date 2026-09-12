"""Offline acceptance: real RSS parser + production pipeline + temporary SQLite."""
import argparse
import hashlib
import json
import platform
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import requests

from src.config import PROJECT_ROOT, load_config
from src.fetchers.rss_fetcher import RSSFetcher
from src.models import NewsItem
from src.notifiers.base import BaseNotifier
from src.pipeline import run_once
from src.processors.classifier import Classifier
from src.processors.deduplicator import generate_news_id
from src.processors.formatter import format_message
from src.storage.sqlite_store import SQLiteStore
from src.utils.logger import setup_logging


class MockNotifier(BaseNotifier):
    def __init__(self):
        self.messages = []

    def send(self, message: str) -> bool:
        self.messages.append(message)
        return True


class FixtureHTTP:
    def __init__(self, content):
        self.content = content

    def get(self, url, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response._content = self.content
        return response


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def run_smoke_test():
    started = datetime.now(timezone.utc)
    config = load_config(PROJECT_ROOT / "config.example.yaml")
    classifier = Classifier(config["filters"])
    news = NewsItem(
        title="Binance announces listing of TEST token",
        link="https://example.com/test-news", source="MockSource",
        published_time="2026-09-11 12:00:00",
        summary="Binance will list TEST token.",
    )
    check(classifier.classify(news) == "P0", "假新闻没有被分为 P0")
    message = format_message(news, "P0")
    check("P0 高优先级" in message and news.link in message and "摘要：" in message, "消息格式错误")
    fixture = (PROJECT_ROOT / "tests" / "fixtures" / "news.xml").read_bytes()
    fetcher = RSSFetcher([{"name": "MockSource", "url": "https://example.com/rss"}], FixtureHTTP(fixture))
    notifier = MockNotifier()
    with TemporaryDirectory(prefix="crypto-news-smoke-") as temp:
        db_path = Path(temp) / "news.db"
        store = SQLiteStore(db_path)
        first = run_once([fetcher], [notifier], classifier, store)
        check(first.fetched == 1 and first.pushed == 1 and first.failed == 0, "首轮解析→分类→推送→入库未完成")
        check(len(notifier.messages) == 1 and news.title in notifier.messages[0], "MockNotifier 未收到正确消息")
        check(store.has_news(generate_news_id(news)), "SQLite 中没有正确的 news_id")
        check(store.count() == 1, "首轮数据库行数应为 1")
        # A fresh store verifies durable deduplication across process restarts.
        second = run_once([fetcher], [notifier], classifier, SQLiteStore(db_path))
        check(second.duplicates == 1 and second.pushed == 0, "第二轮没有跳过重复新闻")
        check(len(notifier.messages) == 1 and store.count() == 1, "重复新闻被再次发送或写入")
    try:
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=5)
        revision = git.stdout.strip() if git.returncode == 0 else "unknown"
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=5)
        working_tree_dirty = bool(dirty.stdout.strip()) if dirty.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        revision, working_tree_dirty = "unknown", None
    return {
        "strategy_id": "crypto-news-bot", "experiment_id": "001-rss-feishu-smoke",
        "run_id": started.strftime("%Y%m%dT%H%M%S%fZ"),
        "hypothesis_id": None, "mode": "synthetic",
        "code_version": revision, "working_tree_dirty": working_tree_dirty,
        "python_version": platform.python_version(),
        "input_sha256": hashlib.sha256(fixture).hexdigest(),
        "config_sha256": hashlib.sha256((PROJECT_ROOT / "config.example.yaml").read_bytes()).hexdigest(),
        "started_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
        "parameters": {"rounds": 2, "notifier": "mock", "database": "temporary SQLite"},
        "metrics": {"first_round": asdict(first), "second_round": asdict(second), "messages_received": len(notifier.messages)},
        "result": "passed",
        "conclusion": "离线最小闭环通过；不代表真实 RSS 或真实飞书群推送已验收。",
    }


def main():
    parser = argparse.ArgumentParser(description="离线 smoke test，无外部网络请求")
    parser.add_argument("--report", type=Path, help="可选：保存 JSON 验收记录")
    args = parser.parse_args()
    setup_logging()
    try:
        report = run_smoke_test()
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"验收记录：{args.report.resolve()}")
    except Exception as exc:
        print(f"SMOKE TEST FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
