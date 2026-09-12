import json
import logging
import sqlite3
import threading
from contextlib import closing
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
import yaml

import main as entrypoint
from smoke_test import FixtureHTTP, MockNotifier, run_smoke_test
from src.config import ConfigError, PROJECT_ROOT, load_config
from src.fetchers.rss_fetcher import RSSFetcher
from src.models import NewsItem
from src.notifiers import build_notifiers
from src.notifiers.feishu import FeishuNotifier
from src.pipeline import run_once
from src.processors.classifier import Classifier
from src.processors.deduplicator import generate_news_id
from src.processors.formatter import format_message
from src.storage.sqlite_store import SQLiteStore


@pytest.fixture
def classifier():
    return Classifier(load_config(PROJECT_ROOT / "config.example.yaml")["filters"])


@pytest.fixture
def store(tmp_path):
    return SQLiteStore(tmp_path / "news.db")


def item(title="Binance announces listing", link="https://example.com/news", **fields):
    return NewsItem(title=title, link=link, source="Test", **fields)


def fetcher(*items):
    result = Mock()
    result.fetch.return_value = list(items)
    result.last_errors = 0
    return result


def response(body=None, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body if body is not None else {"code": 0}).encode()
    return result


def write_config(tmp_path, **overrides):
    config = yaml.safe_load((PROJECT_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    config.update(overrides)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def test_smoke_acceptance():
    report = run_smoke_test()
    assert report["result"] == "passed"
    assert report["metrics"]["messages_received"] == 1


@pytest.mark.parametrize("title,summary,raw,expected", [
    ("binance announces listing", None, None, "P0"),
    ("Market report", "sEc lawsuit", None, "P0"),
    ("Market report", None, "<p>USDT exploit</p>", "P0"),
    ("sponsored Binance giveaway", None, None, "P0"),
    ("New mainnet partnership", None, None, "P1"),
    ("sponsored mainnet", None, None, "P1"),
    ("price prediction and giveaway", None, None, "IGNORE"),
    ("Market AMA today", None, None, "IGNORE"),
    ("A second dramatic day", None, None, "P2"),
    ("Market overview", None, None, "P2"),
])
def test_classification(classifier, title, summary, raw, expected):
    assert classifier.classify(item(title, summary=summary, raw_content=raw)) == expected


def test_formatter_plain_text_and_missing_fields():
    message = format_message(item("<b>Binance</b>", summary=None), "P0")
    assert "暂无摘要" in message and "未知时间" in message
    assert "<b>" not in message and "P0 高优先级" in message
    long = format_message(item("文" * 3000, summary="文" * 20000), "P0")
    assert len(long.encode("utf-8")) < 20000


def test_link_identity_and_title_source_fallback():
    assert generate_news_id(item()) == generate_news_id(item("Changed title"))
    a = item(link="")
    assert generate_news_id(a) == generate_news_id(replace(a))
    assert generate_news_id(a) != generate_news_id(replace(a, source="Other"))
    assert generate_news_id(a) != generate_news_id(replace(a, title="Other"))


def test_durable_dedup_and_same_batch(classifier, store):
    news = item()
    notifier = MockNotifier()
    first = run_once([fetcher(news, replace(news, source="Other"))], [notifier], classifier, store)
    assert first.pushed == 1 and first.duplicates == 1
    second = run_once([fetcher(news)], [notifier], classifier, SQLiteStore(store.path))
    assert second.duplicates == 1 and len(notifier.messages) == 1
    with closing(sqlite3.connect(store.path)) as conn:
        row = conn.execute("SELECT title, link, source, priority, pushed_at FROM pushed_news").fetchone()
    assert row[:4] == (news.title, news.link, news.source, "P0")
    assert row[4].endswith("+00:00")


def test_failed_delivery_is_retried_next_round(classifier, store):
    news = item()
    notifier = Mock()
    notifier.send.side_effect = [False, True]
    first = run_once([fetcher(news, news)], [notifier], classifier, store)
    assert first.failed == 1 and first.duplicates == 1 and store.count() == 0
    second = run_once([fetcher(news)], [notifier], classifier, store)
    assert second.pushed == 1 and store.count() == 1


def test_bad_item_and_notifier_exception_do_not_stop_later_items(classifier, store):
    notifier = Mock()
    notifier.send.side_effect = [RuntimeError("broken adapter"), True]
    stats = run_once([fetcher(None, item(), item(link="https://example.com/next"))], [notifier], classifier, store)
    assert stats.failed == 2 and stats.pushed == 1 and store.count() == 1


@pytest.mark.parametrize("dry_run,with_notifier", [(True, True), (False, False)])
def test_preview_does_not_mark_delivered(classifier, store, dry_run, with_notifier):
    notifier = MockNotifier()
    stats = run_once([fetcher(item())], [notifier] if with_notifier else [], classifier, store, dry_run=dry_run)
    assert stats.previewed == 1 and stats.pushed == 0 and store.count() == 0
    assert notifier.messages == []


def test_p2_ignore_skip_and_p1_push(classifier, store):
    notifier = MockNotifier()
    stats = run_once([fetcher(item("Market overview", "a"), item("giveaway", "b"), item("mainnet", "c"))], [notifier], classifier, store)
    assert (stats.ignored, stats.low_priority, stats.pushed) == (1, 1, 1)
    assert "P1" in notifier.messages[0]


@pytest.mark.parametrize("body,expected", [
    ({"code": 0}, True), ({"StatusCode": 0}, True),
    ({"code": 19024}, False), ({}, False), ([], False),
    ({"code": 0, "StatusCode": 1}, False), ({"code": False}, False),
])
def test_feishu_business_response(body, expected):
    http = Mock()
    http.post.return_value = response(body)
    assert FeishuNotifier("https://example.com/secret", http).send("test") is expected
    http.post.assert_called_once_with("https://example.com/secret", json={"msg_type": "text", "content": {"text": "test"}}, timeout=10)


@pytest.mark.parametrize("failure", ["timeout", "http", "json"])
def test_feishu_failure_and_log_redaction(failure, caplog):
    http = Mock()
    secret = "PRIVATE-WEBHOOK-TOKEN"
    if failure == "timeout":
        http.post.side_effect = requests.Timeout(f"url https://example.com/{secret}")
    else:
        http.post.return_value = response(status=500 if failure == "http" else 200)
        if failure == "json":
            http.post.return_value._content = b"not json"
    with caplog.at_level(logging.ERROR):
        assert not FeishuNotifier(f"https://example.com/{secret}", http).send("test")
    assert "推送失败" in caplog.text and secret not in caplog.text


def test_rss_failed_source_and_missing_fields():
    xml = b'''<rss version="2.0"><channel><title>Test</title>
      <item><title>Only title</title></item>
      <item><link>/relative</link><description>&lt;p&gt;Hello&lt;/p&gt;</description></item>
      <item><description>Empty identity</description></item>
    </channel></rss>'''
    http = Mock()
    http.get.side_effect = [requests.Timeout(), FixtureHTTP(xml).get("unused")]
    rss = RSSFetcher([{"name": "Broken", "url": "https://broken.invalid/rss"}, {"name": "Good", "url": "https://example.com/rss"}], http)
    items = rss.fetch()
    assert rss.last_errors == 1 and len(items) == 2
    assert items[0].title == "Only title" and items[0].link == "" and items[0].published_time is None
    assert items[1].link == "https://example.com/relative" and items[1].summary == "Hello"


def test_atom_and_disabled_rss():
    xml = b'''<feed xmlns="http://www.w3.org/2005/Atom"><title>Test</title><entry>
      <title>Upgrade</title><link href="https://example.com/atom"/>
      <updated>2026-09-11T00:00:00Z</updated><content type="html">&lt;p&gt;Mainnet upgrade&lt;/p&gt;</content>
    </entry></feed>'''
    http = Mock()
    http.get.return_value = FixtureHTTP(xml).get("unused")
    rss = RSSFetcher([{"enabled": False}, {"name": "Atom", "url": "https://example.com/feed"}], http)
    news = rss.fetch()[0]
    assert news.raw_content == "Mainnet upgrade" and news.published_time == "2026-09-11T00:00:00Z"
    assert http.get.call_count == 1


def test_all_sources_fail_normally(classifier, store):
    http = Mock()
    http.get.side_effect = requests.ConnectionError()
    rss = RSSFetcher([{"name": "Down", "url": "https://example.com/rss"}], http)
    stats = run_once([rss], [MockNotifier()], classifier, store)
    assert stats.source_errors == 1 and stats.fetched == 0 and store.count() == 0


def test_html_response_is_failed_feed():
    rss = RSSFetcher([{"name": "HTML", "url": "https://example.com/feed"}], FixtureHTTP(b"<html>Access denied</html>"))
    assert rss.fetch() == [] and rss.last_errors == 1


def test_config_relative_database_and_missing_webhook(tmp_path, caplog):
    config = load_config(write_config(tmp_path))
    assert Path(config["database"]["path"]) == (tmp_path / "data" / "news.db").resolve()
    with caplog.at_level(logging.WARNING):
        assert build_notifiers(config) == []
    assert "Webhook 未配置" in caplog.text


@pytest.mark.parametrize("override", [
    {"app": {"interval_minutes": 0}}, {"app": {"timezone": "not-a-zone"}},
    {"app": {"run_once": "false"}}, {"filters": {"high_priority_keywords": "Binance"}},
    {"sources": {"rss": [{"name": "Wrong", "url": "not a url"}]}},
    {"notifiers": {"telegram": {"enabled": True}}},
    {"notifiers": {"feishu": {"enabled": True, "webhook_url": 123}}},
])
def test_invalid_config(tmp_path, override):
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, **override))


def test_missing_or_malformed_config_is_readable(tmp_path, caplog):
    assert entrypoint.main(["--config", str(tmp_path / "missing.yaml"), "--once"]) == 2
    assert "config.example.yaml" in caplog.text
    path = tmp_path / "bad.yaml"
    path.write_text('notifiers: [PRIVATE-TOKEN\n', encoding="utf-8")
    with pytest.raises(ConfigError) as error:
        load_config(path)
    assert "PRIVATE-TOKEN" not in str(error.value)


def test_once_cli_without_webhook_and_all_sources_failed(tmp_path, monkeypatch):
    failed = fetcher()
    failed.fetch.side_effect = RuntimeError()
    monkeypatch.setattr(entrypoint, "build_fetchers", lambda config: [failed])
    path = write_config(tmp_path)
    assert entrypoint.main(["--config", str(path), "--once"]) == 0
    assert SQLiteStore(tmp_path / "data" / "news.db").count() == 0


def test_scheduler_runs_initial_job_and_limits_overlap(tmp_path, monkeypatch, classifier):
    source = fetcher(item())
    monkeypatch.setattr(entrypoint, "build_fetchers", lambda config: [source])
    scheduler = Mock()
    monkeypatch.setattr(entrypoint, "BlockingScheduler", lambda **kwargs: scheduler)
    assert entrypoint.main(["--config", str(write_config(tmp_path))]) == 0
    assert source.fetch.call_count == 1
    scheduler.start.assert_called_once()
    assert scheduler.add_job.call_args.kwargs["max_instances"] == 1
    assert scheduler.add_job.call_args.kwargs["coalesce"] is True
    # Exercise the callback on a worker thread, like APScheduler does.
    worker = threading.Thread(target=scheduler.add_job.call_args.args[0])
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive() and source.fetch.call_count == 2


def test_http_rss_to_webhook_to_database(tmp_path, monkeypatch):
    """Real loopback HTTP exercises requests, feedparser and Feishu JSON together."""
    received = []
    xml = (PROJECT_ROOT / "tests" / "fixtures" / "news.xml").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.end_headers()
            self.wfile.write(xml)

        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"code":0,"msg":"success"}')

        def log_message(self, *args):
            pass

    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        path = write_config(tmp_path,
            sources={"rss": [{"name": "Loopback", "url": base + "/rss", "enabled": True}]},
            notifiers={"feishu": {"enabled": True, "webhook_url": base + "/hook"}})
        assert entrypoint.main(["--config", str(path), "--once"]) == 0
        assert entrypoint.main(["--config", str(path), "--once"]) == 0
        assert len(received) == 1 and received[0]["msg_type"] == "text"
        assert "P0 高优先级" in received[0]["content"]["text"]
        assert SQLiteStore(tmp_path / "data" / "news.db").count() == 1
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
