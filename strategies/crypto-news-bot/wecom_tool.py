"""Read credentials from YAML; check auth, discover a group, or send one test."""
import argparse
import logging
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from live_verify import write_json
from src.config import ConfigError, load_config
from src.notifiers.wecom import WeComNotifier
from src.utils.logger import setup_logging

TEST_MESSAGE = "策略研究工作台：企业微信长连接测试。收到这条消息表示 Bot 认证与主动推送已连通。"
logger = logging.getLogger(__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description="企业微信长连接联调，默认只检查认证，不发送消息")
    parser.add_argument("--config", help="本地 config.yaml 路径")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--discover", action="store_true", help="接收群回调并列出 chat_id，请在目标群 @机器人")
    actions.add_argument("--send-test", action="store_true", help="向已配置 chat_id 发送一条明确标注的测试消息")
    parser.add_argument("--seconds", type=int, default=60, help="发现群会话的等待秒数，默认 60")
    args = parser.parse_args(argv)
    setup_logging()
    notifier = None
    try:
        config = load_config(args.config)
        settings = deepcopy(config.get("notifiers", {}).get("wecom", {}))
        for key in ("bot_id", "secret"):
            if not isinstance(settings.get(key), str) or not settings[key].strip():
                raise ConfigError(f"请先在本地 config.yaml 填写 notifiers.wecom.{key}；获取 chat_id 前可保持 enabled: false。")
        if not 1 <= args.seconds <= 600:
            raise ConfigError("--seconds 必须为 1 到 600")
        if args.send_test and not str(settings.get("chat_id", "")).strip():
            raise ConfigError("请先填写目标群 chat_id；可运行 npm run news:wecom -- --discover 获取。")
        # Validate connection options even when the channel is disabled for news.
        from src.config import validate_wecom
        validate_wecom(settings, require_chat=False)
        notifier = WeComNotifier(settings["bot_id"], settings["secret"], settings.get("chat_id", ""),
                                 ws_url=settings.get("ws_url", "wss://openws.work.weixin.qq.com"),
                                 timeout_seconds=settings.get("timeout_seconds", 10),
                                 heartbeat_seconds=settings.get("heartbeat_seconds", 30))
        if not notifier.wait_ready():
            logger.error("企业微信未完成认证，未发送消息")
            return 1
        run_dir = Path(config["database"]["path"]).parent / "runs"
        if args.discover:
            print(f"认证成功。请在目标企业微信群 @机器人；等待 {args.seconds} 秒。", flush=True)
            deadline = time.monotonic() + args.seconds
            known = set()
            while time.monotonic() < deadline:
                for chat_id in notifier.discovered_groups():
                    if chat_id not in known:
                        known.add(chat_id)
                        print(f"发现群 chat_id：{chat_id}", flush=True)
                time.sleep(0.2)
            groups = sorted(set(notifier.discovered_groups()) | known)
            path = run_dir / "wecom-groups.json"
            write_json(path, {"groups": groups, "checked_at": datetime.now(timezone.utc).isoformat()})
            print(f"群标识已保存：{path}；选择目标群后将其填入 config.yaml 的 chat_id。")
            return 0 if groups else 1
        if args.send_test:
            success = notifier.send(TEST_MESSAGE)
            path = run_dir / "wecom-verification.json"
            write_json(path, {"authenticated": True, "send_confirmed": success,
                              "destination_id": notifier.delivery_key, "message": TEST_MESSAGE,
                              "checked_at": datetime.now(timezone.utc).isoformat()})
            print(f"企业微信测试消息接口确认：{success}；记录：{path}")
            return 0 if success else 1
        print("企业微信长连接认证成功；本次未发送消息。")
        return 0
    except ConfigError as exc:
        logger.error("企业微信配置错误：%s", exc)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logger.error("企业微信联调失败（%s）", type(exc).__name__)
        return 1
    finally:
        if notifier:
            notifier.close()


if __name__ == "__main__":
    raise SystemExit(main())
