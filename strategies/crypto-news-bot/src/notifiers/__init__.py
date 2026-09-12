import logging

from .feishu import FeishuNotifier
from .wecom import WeComNotifier

logger = logging.getLogger(__name__)
NOTIFIER_FACTORIES = {
    "feishu": lambda settings: FeishuNotifier(settings.get("webhook_url", "")),
    "wecom": lambda settings: WeComNotifier(
        settings["bot_id"], settings["secret"], settings.get("chat_id", ""),
        ws_url=settings.get("ws_url", "wss://openws.work.weixin.qq.com"),
        timeout_seconds=settings.get("timeout_seconds", 10),
        heartbeat_seconds=settings.get("heartbeat_seconds", 30),
    ),
}


def build_notifiers(config):
    notifiers = []
    for name, settings in config.get("notifiers", {}).items():
        if not settings.get("enabled", True):
            continue
        if name == "feishu" and not settings.get("webhook_url", "").strip():
            logger.warning("飞书 Webhook 未配置：请在 config.yaml 的 notifiers.feishu.webhook_url 填写地址；本轮仅预览，不标记已推送。")
            continue
        notifiers.append(NOTIFIER_FACTORIES[name](settings))
    return notifiers


def start_notifiers(notifiers):
    for notifier in notifiers:
        start = getattr(notifier, "start", None)
        if callable(start):
            start()


def close_notifiers(notifiers):
    for notifier in notifiers:
        try:
            close = getattr(notifier, "close", None)
            if callable(close):
                close()
        except Exception as exc:
            logger.warning("关闭通知器失败（%s）", type(exc).__name__)
