import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

from src.config import ConfigError, validate_wecom
from src.notifiers.base import BaseNotifier
from src.notifiers.wecom import WeComNotifier
from src.pipeline import run_once
from src.models import NewsItem
from src.processors.classifier import Classifier
from src.processors.deduplicator import generate_news_id
from src.storage.sqlite_store import SQLiteStore
from live_verify import PreparedFetcher


@pytest.fixture(autouse=True)
def no_external_wecom(monkeypatch):
    import websockets.sync.client
    from urllib.parse import urlsplit
    original = websockets.sync.client.connect

    def local_connect(uri, **kwargs):
        assert urlsplit(uri).hostname == "127.0.0.1", "No real WeCom in tests"
        kwargs["proxy"] = None
        return original(uri, **kwargs)

    monkeypatch.setattr(websockets.sync.client, "connect", local_connect)


def ack(ws, frame, code=0):
    ws.send(json.dumps({"headers": frame["headers"], "errcode": code}))


@contextmanager
def server(handler):
    def safe_handler(ws):
        try:
            handler(ws)
        except ConnectionClosed:
            pass

    with serve(safe_handler, "127.0.0.1", 0, ping_interval=None) as instance:
        thread = threading.Thread(target=instance.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"ws://127.0.0.1:{instance.socket.getsockname()[1]}"
        finally:
            instance.shutdown()
            thread.join(timeout=3)


def client(url, **kwargs):
    return WeComNotifier("test-bot", "PRIVATE-SECRET", "group-123", ws_url=url,
                         timeout_seconds=kwargs.get("timeout", 0.5), heartbeat_seconds=kwargs.get("heartbeat", 0.1),
                         reconnect_seconds=0.02)


def test_socket_auth_send_receipt_heartbeat_discovery_and_close(caplog):
    frames = []
    ping_received = threading.Event()

    def handler(ws):
        auth = json.loads(ws.recv(timeout=2))
        frames.append(auth)
        ack(ws, auth)
        ws.send(json.dumps({"cmd": "aibot_msg_callback", "headers": {"req_id": "incoming"},
                            "body": {"chattype": "group", "chatid": "target-group", "text": {"content": "PRIVATE-INCOMING-TEXT"}}}))
        for raw in ws:
            frame = json.loads(raw)
            frames.append(frame)
            if frame["cmd"] == "ping":
                ping_received.set()
            ack(ws, frame)

    with caplog.at_level(logging.DEBUG), server(handler) as url:
        bot = client(url)
        try:
            assert bot.wait_ready()
            assert bot.send("测试一") and bot.send("测试二")
            assert ping_received.wait(2)
            assert bot.discovered_groups() == ["target-group"]
        finally:
            bot.close()
        assert not bot._thread.is_alive()
    assert frames[0]["cmd"] == "aibot_subscribe"
    assert frames[0]["body"] == {"bot_id": "test-bot", "secret": "PRIVATE-SECRET"}
    messages = [f for f in frames if f["cmd"] == "aibot_send_msg"]
    assert len(messages) == 2
    assert messages[0]["body"] == {"chatid": "group-123", "msgtype": "markdown", "markdown": {"content": "测试一"}}
    assert len([f for f in frames if f["cmd"] == "aibot_subscribe"]) == 1
    # The simulated recipient intentionally receives credentials. Check client logs,
    # excluding the test server's own frame dump from the same Python process.
    client_logs = "\n".join(record.getMessage() for record in caplog.records if record.name != "websockets.server")
    assert "PRIVATE-SECRET" not in client_logs and "PRIVATE-INCOMING-TEXT" not in client_logs


@pytest.mark.parametrize("failure", ["reject", "timeout", "wrong_req_id"])
def test_failed_receipt_never_returns_success_or_replays(failure):
    sent = []

    def handler(ws):
        ack(ws, json.loads(ws.recv(timeout=2)))
        for raw in ws:
            frame = json.loads(raw)
            if frame["cmd"] == "aibot_send_msg":
                sent.append(frame)
                if failure == "reject":
                    ack(ws, frame, 40001)
                elif failure == "wrong_req_id":
                    ws.send(json.dumps({"headers": {"req_id": "wrong"}, "errcode": 0}))
            else:
                ack(ws, frame)

    with server(handler) as url:
        bot = client(url)
        try:
            assert not bot.send("Test")
            assert len(sent) == 1
        finally:
            bot.close()


def test_authentication_failure_is_not_connection_success():
    def handler(ws):
        ack(ws, json.loads(ws.recv(timeout=2)), 40001)
        for raw in ws:
            pytest.fail("Must not send after rejected authentication")

    with server(handler) as url:
        bot = client(url)
        try:
            assert not bot.wait_ready()
            assert not bot.send("Never send")
        finally:
            bot.close()


@pytest.mark.parametrize("reason", ["normal_close", "heartbeat_timeout"])
def test_reconnect_and_reauthenticate(reason):
    connections = []
    reconnected = threading.Event()

    def handler(ws):
        auth = json.loads(ws.recv(timeout=2))
        connections.append(auth)
        first = len(connections) == 1
        ack(ws, auth)
        if first and reason == "normal_close":
            ws.close()
            return
        if not first:
            reconnected.set()
        for raw in ws:
            frame = json.loads(raw)
            if first and reason == "heartbeat_timeout" and frame["cmd"] == "ping":
                continue
            ack(ws, frame)

    with server(handler) as url:
        bot = client(url, timeout=0.3, heartbeat=0.05)
        try:
            bot.start()
            assert reconnected.wait(3)
            assert bot.send("After reconnect")
            assert len(connections) >= 2
        finally:
            bot.close()


def test_long_message_preserves_link_and_byte_limit():
    bodies = []

    def handler(ws):
        ack(ws, json.loads(ws.recv(timeout=2)))
        for raw in ws:
            frame = json.loads(raw)
            if frame["cmd"] == "aibot_send_msg":
                bodies.append(frame["body"])
            ack(ws, frame)

    with server(handler) as url:
        bot = client(url)
        try:
            assert bot.send("内容" * 3000 + "\n链接：https://example.com/news")
        finally:
            bot.close()
    content = bodies[0]["markdown"]["content"]
    assert len(content.encode()) < 4096 and content.endswith("https://example.com/news")


@pytest.mark.parametrize("changes", [{"bot_id": ""}, {"secret": ""}, {"chat_id": ""},
                                    {"ws_url": "http://example.com"}, {"timeout_seconds": 0},
                                    {"heartbeat_seconds": False}, {"chat_id": 12}])
def test_wecom_configuration_validation(changes):
    config = {"bot_id": "b", "secret": "s", "chat_id": "g", **changes}
    with pytest.raises(ConfigError):
        validate_wecom(config)


class NamedNotifier(BaseNotifier):
    def __init__(self, key, success=True):
        self.delivery_key = key
        self.success = success
        self.messages = []

    def send(self, message):
        self.messages.append(message)
        return self.success


def test_partial_channel_failure_only_retries_failed_channel(tmp_path):
    store = SQLiteStore(tmp_path / "db.sqlite")
    news = NewsItem("Binance listing", "https://example.com/news", "Test")
    classifier = Classifier({"high_priority_keywords": ["Binance"]})
    feishu = NamedNotifier("feishu:test")
    wecom = NamedNotifier("wecom:test", False)
    first = run_once([PreparedFetcher(news)], [feishu, wecom], classifier, store)
    assert first.failed == 1 and store.count() == 0
    assert store.has_delivery(generate_news_id(news), "feishu:test")
    wecom.success = True
    second = run_once([PreparedFetcher(news)], [feishu, wecom], classifier, SQLiteStore(store.path))
    assert second.pushed == 1 and len(feishu.messages) == 1 and len(wecom.messages) == 2
    third = run_once([PreparedFetcher(news)], [feishu, wecom], classifier, store)
    assert third.duplicates == 1 and len(wecom.messages) == 2


def test_new_destination_gets_news_without_replaying_existing_destination(tmp_path):
    store = SQLiteStore(tmp_path / "db.sqlite")
    news = NewsItem("Binance", "https://example.com/news", "Test")
    classifier = Classifier({"high_priority_keywords": ["Binance"]})
    old = NamedNotifier("wecom:old-group")
    run_once([PreparedFetcher(news)], [old], classifier, store)
    new = NamedNotifier("feishu:new-group")
    run_once([PreparedFetcher(news)], [old, new], classifier, SQLiteStore(store.path))
    assert len(old.messages) == 1 and len(new.messages) == 1


def test_legacy_feishu_migration_preserves_history_and_allows_wecom(tmp_path):
    path = tmp_path / "old.sqlite"
    news = NewsItem("Binance", "https://example.com/news", "Test")
    news_id = generate_news_id(news)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE pushed_news (id INTEGER PRIMARY KEY, news_id TEXT UNIQUE, title TEXT, link TEXT, source TEXT, priority TEXT, pushed_at TEXT)")
        conn.execute("INSERT INTO pushed_news VALUES (1, ?, ?, ?, ?, 'P0', '2026-09-12')", (news_id, news.title, news.link, news.source))
    store = SQLiteStore(path)
    feishu, wecom = NamedNotifier("feishu:existing"), NamedNotifier("wecom:new")
    run_once([PreparedFetcher(news)], [feishu, wecom], Classifier({"high_priority_keywords": ["Binance"]}), store)
    assert feishu.messages == [] and len(wecom.messages) == 1 and store.count() == 1
    assert SQLiteStore(path).has_delivery(news_id, "feishu:existing")


def test_secret_rotation_does_not_change_destination_identity():
    a = WeComNotifier("bot", "old-secret", "group")
    b = WeComNotifier("bot", "new-secret", "group")
    assert a.delivery_key == b.delivery_key
