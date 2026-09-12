import json
from dataclasses import asdict
from unittest.mock import Mock

import pytest

import live_verify
from smoke_test import MockNotifier
from src.config import ConfigError, PROJECT_ROOT, load_config
from src.models import NewsItem
from src.storage.sqlite_store import SQLiteStore


@pytest.fixture
def config(tmp_path):
    config = load_config(PROJECT_ROOT / "config.example.yaml")
    config["database"]["path"] = str(tmp_path / "news.db")
    config["notifiers"]["feishu"]["webhook_url"] = "https://example.com/PRIVATE-TEST-KEY"
    return config


@pytest.fixture
def pending(tmp_path):
    return tmp_path / "pending.json"


def set_feed(monkeypatch, items):
    feed = Mock(last_errors=0)
    feed.fetch.return_value = items
    monkeypatch.setattr(live_verify, "build_fetchers", lambda config: [feed])
    return feed


def news(title="Binance listing", link="https://example.com/news"):
    return NewsItem(title=title, link=link, source="Synthetic")


def prepared(monkeypatch, config, pending):
    set_feed(monkeypatch, [news()])
    return live_verify.prepare(config, pending)


def test_prepare_one_p0_without_notifying_or_storing(monkeypatch, config, pending):
    set_feed(monkeypatch, [news("mainnet", "https://example.com/p1"), news(), news()])
    build = Mock(side_effect=AssertionError("Must not initialize a live notifier"))
    monkeypatch.setattr(live_verify, "build_notifiers", build)
    snapshot = live_verify.prepare(config, pending)
    assert snapshot["candidate_count"] == 2
    assert snapshot["news"] == asdict(news()) and snapshot["priority"] == "P0"
    assert snapshot["ready"] and snapshot["fetched"] == 3
    assert not build.called and SQLiteStore(config["database"]["path"]).count() == 0
    assert "PRIVATE-TEST-KEY" not in pending.read_text(encoding="utf-8")


def test_send_saved_news_once_and_check_dedup(monkeypatch, config, pending, tmp_path):
    prepared(monkeypatch, config, pending)
    monkeypatch.setattr(live_verify, "build_fetchers", Mock(side_effect=AssertionError("Must use saved item")))
    notifier = MockNotifier()
    monkeypatch.setattr(live_verify, "build_notifiers", lambda config: [notifier])
    report_path = tmp_path / "receipt.json"
    first = live_verify.verify(config, pending, report_path)
    assert first["result"] == "passed"
    assert first["first_round"]["pushed"] == 1 and first["second_round"]["duplicates"] == 1
    assert first["database_rows_before"] == 0 and first["database_rows_after"] == 1
    assert len(notifier.messages) == 1
    again = live_verify.verify(config, pending, report_path)
    assert again["result"] == "already_pushed" and len(notifier.messages) == 1
    assert "PRIVATE-TEST-KEY" not in report_path.read_text(encoding="utf-8")


def test_send_failure_is_recorded_without_retry(monkeypatch, config, pending, tmp_path):
    prepared(monkeypatch, config, pending)
    notifier = Mock()
    notifier.send.return_value = False
    monkeypatch.setattr(live_verify, "build_notifiers", lambda config: [notifier])
    report = live_verify.verify(config, pending, tmp_path / "receipt.json")
    assert report["result"] == "failed" and report["database_rows_after"] == 0
    assert "second_round" not in report and notifier.send.call_count == 1


@pytest.mark.parametrize("change", ["message", "destination", "filter", "timestamp"])
def test_reject_changed_snapshot_or_configuration_before_send(monkeypatch, config, pending, tmp_path, change):
    snapshot = prepared(monkeypatch, config, pending)
    if change == "message":
        snapshot["message"] = "Different message"
        live_verify.write_json(pending, snapshot)
    elif change == "destination":
        config["notifiers"]["feishu"]["webhook_url"] = "https://example.com/OTHER-PRIVATE-KEY"
    elif change == "timestamp":
        del snapshot["prepared_at"]
        live_verify.write_json(pending, snapshot)
    else:
        config["filters"]["high_priority_keywords"] = []
    build = Mock()
    monkeypatch.setattr(live_verify, "build_notifiers", build)
    with pytest.raises(ConfigError):
        live_verify.verify(config, pending, tmp_path / "receipt.json")
    assert not build.called


def test_empty_round_invalidates_previous_pending(monkeypatch, config, pending):
    prepared(monkeypatch, config, pending)
    set_feed(monkeypatch, [])
    assert not live_verify.prepare(config, pending)["ready"]
    with pytest.raises(ConfigError):
        live_verify.read_pending(config, pending)


def test_prepare_skips_pushed_and_handles_failed_sources(monkeypatch, config, pending):
    initial = prepared(monkeypatch, config, pending)
    store = SQLiteStore(config["database"]["path"])
    store.mark_pushed(initial["news_id"], news(), "P0")
    store.mark_delivery(initial["news_id"], "feishu:" + initial["destination_sha256"])
    assert not live_verify.prepare(config, pending)["ready"]
    feed = set_feed(monkeypatch, [])
    feed.fetch.side_effect = RuntimeError("source unavailable")
    snapshot = live_verify.prepare(config, pending)
    assert not snapshot["ready"] and snapshot["source_errors"] == 1


def test_unconfigured_webhook_and_missing_pending(config, pending):
    with pytest.raises(ConfigError):
        live_verify.read_pending(config, pending)
    config["notifiers"]["feishu"]["webhook_url"] = ""
    with pytest.raises(ConfigError, match="Webhook"):
        live_verify.prepare(config, pending)


def test_verify_cli_default_only_prepares(monkeypatch, config, pending, capsys):
    set_feed(monkeypatch, [news()])
    monkeypatch.setattr(live_verify, "load_config", lambda path: config)
    assert live_verify.main(["--pending", str(pending)]) == 0
    assert "当前未发送" in capsys.readouterr().out
    assert json.loads(pending.read_text(encoding="utf-8"))["ready"]
