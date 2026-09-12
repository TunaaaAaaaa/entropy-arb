import logging
from dataclasses import asdict, dataclass

from .processors.deduplicator import generate_news_id
from .processors.formatter import format_message

logger = logging.getLogger(__name__)


@dataclass
class RunStats:
    fetched: int = 0
    source_errors: int = 0
    duplicates: int = 0
    ignored: int = 0
    low_priority: int = 0
    candidates: int = 0
    previewed: int = 0
    pushed: int = 0
    failed: int = 0


def run_once(fetchers, notifiers, classifier, store, dry_run=False) -> RunStats:
    stats = RunStats()
    attempted = set()
    preview = dry_run or not notifiers
    keys = [getattr(notifier, "delivery_key", None) for notifier in notifiers]
    channel_tracking = bool(keys) and all(isinstance(key, str) and key for key in keys)
    if channel_tracking:
        for key in keys:
            if key.startswith("feishu:"):
                store.bind_legacy_feishu(key)

    def already_delivered(news_id):
        if channel_tracking:
            return all(store.has_delivery(news_id, key) for key in keys)
        return store.has_news(news_id)

    if not notifiers and not dry_run:
        logger.warning("没有可用通知器：只预览候选新闻，不写入已推送表。")
    for fetcher in fetchers:
        try:
            items = fetcher.fetch()
            stats.source_errors += getattr(fetcher, "last_errors", 0)
        except Exception as exc:
            stats.source_errors += 1
            logger.error("数据源失败（%s），继续本轮", type(exc).__name__)
            continue
        for news in items:
            stats.fetched += 1
            try:
                news_id = generate_news_id(news)
                if news_id in attempted or already_delivered(news_id):
                    stats.duplicates += 1
                    continue
                priority = classifier.classify(news)
                if priority == "IGNORE":
                    stats.ignored += 1
                    continue
                if priority == "P2":
                    stats.low_priority += 1
                    continue
                attempted.add(news_id)
                stats.candidates += 1
                message = format_message(news, priority)
                if preview:
                    logger.info("[预览，未推送] %s", message)
                    stats.previewed += 1
                    continue
                delivered = True
                for index, notifier in enumerate(notifiers):
                    try:
                        if channel_tracking and store.has_delivery(news_id, keys[index]):
                            continue
                        success = bool(notifier.send(message))
                        if success and channel_tracking:
                            store.mark_delivery(news_id, keys[index])
                        delivered = success and delivered
                    except Exception as exc:
                        delivered = False
                        logger.error("通知器失败（%s），继续后续新闻", type(exc).__name__)
                if delivered:
                    store.mark_pushed(news_id, news, priority)
                    stats.pushed += 1
                    logger.info("推送成功并入库：%s %s", priority, news.title)
                else:
                    stats.failed += 1
                    logger.warning("本条推送未全部成功，不记入已推送表：%s", news.title)
            except Exception as exc:
                stats.failed += 1
                logger.error("单条新闻处理失败（%s），继续后续新闻", type(exc).__name__)
    logger.info("本轮结果：%s", asdict(stats))
    return stats
