import argparse
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from src.config import ConfigError, load_config
from src.fetchers import build_fetchers
from src.notifiers import build_notifiers, close_notifiers, start_notifiers
from src.pipeline import run_once
from src.processors.classifier import Classifier
from src.storage.sqlite_store import SQLiteStore
from src.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description="币圈 RSS 新闻监控与飞书/企业微信推送 V0.2")
    parser.add_argument("--config", help="YAML 配置路径，默认读取子项目 config.yaml")
    parser.add_argument("--once", action="store_true", help="只运行一轮，覆盖 app.run_once")
    parser.add_argument("--dry-run", action="store_true", help="只打印候选消息，不发送、不标记已推送")
    args = parser.parse_args(argv)
    setup_logging()
    try:
        config = load_config(args.config)
        store = SQLiteStore(config["database"]["path"])
        fetchers = build_fetchers(config)
        notifiers = [] if args.dry_run else build_notifiers(config)
        classifier = Classifier(config["filters"])
        scheduler = BlockingScheduler(timezone=config["app"]["timezone"])
    except ConfigError as exc:
        logger.error("配置错误：%s", exc)
        return 2
    except Exception as exc:
        logger.error("初始化失败（%s），请检查依赖和数据库路径权限", type(exc).__name__)
        return 2

    def job():
        try:
            return run_once(fetchers, notifiers, classifier, store, args.dry_run)
        except Exception as exc:
            logger.error("本轮任务失败（%s），等待下一轮", type(exc).__name__)
            return None

    try:
        start_notifiers(notifiers)
        logger.info("%s 已启动；SQLite：%s", config["app"]["name"], store.path)
        job()
        if args.once or config["app"]["run_once"]:
            return 0
        scheduler.add_job(job, "interval", minutes=config["app"]["interval_minutes"],
                          id="collect-news", max_instances=1, coalesce=True)
        logger.info("每 %s 分钟抓取一次，Ctrl+C 停止", config["app"]["interval_minutes"])
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        if scheduler.running:
            scheduler.shutdown(wait=True)
        logger.info("新闻机器人已停止")
    finally:
        close_notifiers(notifiers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
