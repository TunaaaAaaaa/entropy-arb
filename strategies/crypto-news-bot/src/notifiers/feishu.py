import logging
import hashlib

import requests

from .base import BaseNotifier

logger = logging.getLogger(__name__)


class FeishuNotifier(BaseNotifier):
    def __init__(self, webhook_url, session=None):
        self.webhook_url = webhook_url.strip()
        self.http = session or requests
        self.delivery_key = "feishu:" + hashlib.sha256(self.webhook_url.encode("utf-8")).hexdigest()

    def send(self, message: str) -> bool:
        if not self.webhook_url:
            logger.warning("飞书 Webhook 未配置，无法发送")
            return False
        try:
            response = self.http.post(self.webhook_url, json={
                "msg_type": "text", "content": {"text": message},
            }, timeout=10)
            response.raise_for_status()
            result = response.json()
            codes = [result[key] for key in ("code", "StatusCode") if key in result] if isinstance(result, dict) else []
            if codes and all(type(code) is int and code == 0 for code in codes):
                return True
            logger.error("飞书未确认推送成功，请检查机器人配置、关键词/签名限制或频率限制")
        except Exception as exc:
            # Request exception strings can contain the secret webhook URL.
            logger.error("飞书推送失败（%s），保留供下轮重试", type(exc).__name__)
        return False
