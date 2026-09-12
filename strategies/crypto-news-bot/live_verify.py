"""Prepare one real news item; --send explicitly delivers that saved item once."""
import argparse
import hashlib
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from src.config import ConfigError, load_config
from src.fetchers import build_fetchers
from src.fetchers.base import BaseFetcher
from src.models import NewsItem
from src.notifiers import build_notifiers
from src.pipeline import run_once
from src.processors.classifier import Classifier
from src.processors.deduplicator import generate_news_id
from src.processors.formatter import format_message
from src.storage.sqlite_store import SQLiteStore
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


class PreparedFetcher(BaseFetcher):
    def __init__(self, news):
        self.news = news

    def fetch(self):
        return [self.news]


def destination_fingerprint(config):
    settings = config.get("notifiers", {}).get("feishu", {})
    webhook = settings.get("webhook_url", "").strip()
    if not settings.get("enabled", True) or not webhook:
        raise ConfigError("真实联调需要在 config.yaml 启用飞书并填写 Webhook。")
    return hashlib.sha256(webhook.encode("utf-8")).hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(config, pending_path):
    fingerprint = destination_fingerprint(config)
    classifier = Classifier(config["filters"])
    store = SQLiteStore(config["database"]["path"])
    feishu_key = "feishu:" + fingerprint
    store.bind_legacy_feishu(feishu_key)
    candidates = {}
    source_errors = 0
    fetched = 0
    for fetcher in build_fetchers(config):
        try:
            news_items = fetcher.fetch()
            source_errors += getattr(fetcher, "last_errors", 0)
        except Exception as exc:
            logger.error("联调来源失败（%s），继续其他来源", type(exc).__name__)
            source_errors += 1
            continue
        for news in news_items:
            fetched += 1
            try:
                priority = classifier.classify(news)
                news_id = generate_news_id(news)
                if priority in ("P0", "P1") and not store.has_delivery(news_id, feishu_key):
                    previous = candidates.get(news_id)
                    if previous is None or priority < previous[0]:
                        candidates[news_id] = (priority, news)
            except Exception as exc:
                logger.error("联调条目跳过（%s）", type(exc).__name__)
    snapshot = {
        "schema_version": 1,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "destination_sha256": fingerprint,
        "fetched": fetched, "source_errors": source_errors,
        "candidate_count": len(candidates), "ready": bool(candidates),
    }
    if candidates:
        priority, news = min(candidates.values(), key=lambda entry: entry[0])
        snapshot.update({"news": asdict(news), "news_id": generate_news_id(news),
                         "priority": priority, "message": format_message(news, priority)})
    # An empty preparation replaces an older pending item rather than silently reusing it.
    write_json(pending_path, snapshot)
    return snapshot


def read_pending(config, pending_path):
    try:
        snapshot = json.loads(Path(pending_path).read_text(encoding="utf-8"))
        if snapshot.get("schema_version") != 1 or not snapshot.get("ready"):
            raise ValueError()
        if datetime.fromisoformat(snapshot["prepared_at"]).tzinfo is None:
            raise ValueError()
        news = NewsItem(**snapshot["news"])
        priority = snapshot["priority"]
        if priority not in ("P0", "P1") or Classifier(config["filters"]).classify(news) != priority:
            raise ValueError()
        if snapshot["news_id"] != generate_news_id(news) or snapshot["message"] != format_message(news, priority):
            raise ValueError()
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
        raise ConfigError("待发送文件缺失、已修改或已不符合当前筛选规则；请先运行 npm run news:verify 重新准备。") from None
    if snapshot.get("destination_sha256") != destination_fingerprint(config):
        raise ConfigError("飞书发送目标已变化；请先运行 npm run news:verify 重新准备并核对。")
    return snapshot, news


def verify(config, pending_path, report_path):
    snapshot, news = read_pending(config, pending_path)
    store = SQLiteStore(config["database"]["path"])
    # This command verifies the prepared Feishu destination only.
    notifiers = build_notifiers({"notifiers": {"feishu": config["notifiers"]["feishu"]}})
    if len(notifiers) != 1:
        raise ConfigError("V0.1 真实联调需要且只支持一个已配置的飞书通知器。")
    classifier = Classifier(config["filters"])
    key = getattr(notifiers[0], "delivery_key", None)
    if isinstance(key, str) and key.startswith("feishu:"):
        store.bind_legacy_feishu(key)
        existing = store.has_delivery(snapshot["news_id"], key)
    else:
        existing = store.has_news(snapshot["news_id"])
    before = store.count()
    first = run_once([PreparedFetcher(news)], notifiers, classifier, store)
    report = {
        "mode": "live", "checked_at": datetime.now(timezone.utc).isoformat(),
        "news_id": snapshot["news_id"], "title": news.title, "priority": snapshot["priority"],
        "destination_sha256": snapshot["destination_sha256"],
        "prepared_at": snapshot["prepared_at"], "database_rows_before": before,
        "first_round": asdict(first), "result": "failed",
    }
    if first.failed == 0 and (first.pushed == 1 or (existing and first.duplicates == 1)):
        # Only verify dedup after the first round confirms persistence; no retry on failure.
        second = run_once([PreparedFetcher(news)], notifiers, classifier, SQLiteStore(store.path))
        report["second_round"] = asdict(second)
        if second.duplicates == 1 and second.pushed == 0 and second.failed == 0:
            report["result"] = "already_pushed" if existing else "passed"
    report["database_rows_after"] = store.count()
    report["receipt_scope"] = "飞书接口确认和本地入库/去重；不证明群成员已读。"
    write_json(report_path, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="准备一条新闻进行飞书真实联调；默认不发送")
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--send", action="store_true", help="向已配置群发送已保存的一条新闻，并检查入库与去重")
    parser.add_argument("--pending", type=Path, help="待发送快照路径，默认在 SQLite 同目录的 runs 下")
    parser.add_argument("--report", type=Path, help="真实联调结果路径")
    args = parser.parse_args(argv)
    setup_logging()
    try:
        config = load_config(args.config)
        run_dir = Path(config["database"]["path"]).parent / "runs"
        pending = args.pending or run_dir / "feishu-pending.json"
        if args.send:
            report_path = args.report or run_dir / "feishu-verification.json"
            report = verify(config, pending, report_path)
            print(f"真实联调结果：{report['result']}；记录：{report_path.resolve()}")
            return 0 if report["result"] in ("passed", "already_pushed") else 1
        snapshot = prepare(config, pending)
        print(f"解析 {snapshot['fetched']} 条，候选 {snapshot['candidate_count']} 条，来源错误 {snapshot['source_errors']}。")
        if not snapshot["ready"]:
            print("没有未推送的 P0/P1 新闻；未准备发送内容。")
            return 1
        print(snapshot["message"])
        print(f"待发送内容已保存：{pending.resolve()}")
        print("当前未发送。核对内容后运行 npm run news:verify -- --send，仅发送此条并验证去重。")
        return 0
    except ConfigError as exc:
        logger.error("联调配置错误：%s", exc)
        return 2
    except Exception as exc:
        logger.error("联调失败（%s），请检查配置与数据目录权限", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
