"""Load and validate configuration without including secrets in error messages."""
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigError(ValueError):
    pass


def _mapping(value, label):
    if not isinstance(value, dict):
        raise ConfigError(f"{label} 必须是 YAML 对象")
    return value


def _enabled(settings, label):
    if type(settings.get("enabled", True)) is not bool:
        raise ConfigError(f"{label}.enabled 必须是 true 或 false")


def _http_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in ("http", "https") and bool(parsed.hostname)
    except ValueError:
        return False


def validate_wecom(settings, require_chat=True):
    for key in (("bot_id", "secret", "chat_id") if require_chat else ("bot_id", "secret")):
        if not isinstance(settings.get(key), str) or not settings[key].strip():
            raise ConfigError(f"企业微信配置需要 notifiers.wecom.{key}")
    if not isinstance(settings.get("chat_id", ""), str):
        raise ConfigError("企业微信 chat_id 必须为字符串")
    ws_url = settings.setdefault("ws_url", "wss://openws.work.weixin.qq.com")
    try:
        parsed = urlsplit(ws_url)
        valid = parsed.scheme == "wss" and bool(parsed.hostname) and not parsed.username and not parsed.password
    except (TypeError, ValueError, AttributeError):
        valid = False
    if not valid:
        raise ConfigError("企业微信 ws_url 必须是有效的 wss:// 长连接地址")
    for key, default, upper in (("timeout_seconds", 10, 60), ("heartbeat_seconds", 30, 60)):
        value = settings.setdefault(key, default)
        if type(value) not in (int, float) or not 0 < value <= upper:
            raise ConfigError(f"企业微信 {key} 必须是 0 到 {upper} 之间的正数")


def load_config(path=None):
    path = Path(path).resolve() if path else PROJECT_ROOT / "config.yaml"
    if not path.is_file():
        raise ConfigError(f"找不到配置 {path}。请先复制 config.example.yaml 为 config.yaml。")
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f"（第 {mark.line + 1} 行）" if mark else ""
        raise ConfigError(f"配置 YAML 格式错误{location}，请检查缩进。") from None
    except (OSError, UnicodeError):
        raise ConfigError("无法读取配置文件，请检查权限与 UTF-8 编码。") from None
    config = _mapping(config, "config")
    app = _mapping(config.setdefault("app", {}), "app")
    app.setdefault("name", "crypto-news-bot")
    interval = app.setdefault("interval_minutes", 10)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not 0 < interval <= 525600:
        raise ConfigError("app.interval_minutes 必须是 0 到 525600 之间的正数")
    if type(app.setdefault("run_once", False)) is not bool:
        raise ConfigError("app.run_once 必须是 true 或 false")
    try:
        ZoneInfo(app.setdefault("timezone", "Asia/Shanghai"))
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ConfigError("app.timezone 无效；可使用 Asia/Shanghai 或 UTC。") from None
    database = _mapping(config.setdefault("database", {}), "database")
    db_path = database.setdefault("path", "data/news.db")
    if not isinstance(db_path, str) or not db_path.strip() or db_path == ":memory:":
        raise ConfigError("database.path 必须是 SQLite 文件路径")
    database["path"] = str((path.parent / db_path).resolve())
    sources = _mapping(config.setdefault("sources", {}), "sources")
    for kind, entries in sources.items():
        if kind != "rss":
            raise ConfigError(f"V0.1 尚未实现数据源：{kind}")
        if not isinstance(entries, list):
            raise ConfigError("sources.rss 必须是列表")
        for entry in entries:
            entry = _mapping(entry, "RSS source")
            _enabled(entry, "RSS source")
            if not entry.get("enabled", True):
                continue
            if not isinstance(entry.get("name"), str) or not entry["name"].strip():
                raise ConfigError("已启用 RSS 源需要 name")
            if not _http_url(entry.get("url")):
                raise ConfigError("已启用 RSS 源需要有效 HTTP(S) URL")
    filters = _mapping(config.setdefault("filters", {}), "filters")
    for key in ("high_priority_keywords", "medium_priority_keywords", "ignore_keywords"):
        keywords = filters.setdefault(key, [])
        if not isinstance(keywords, list) or any(not isinstance(k, str) or not k.strip() for k in keywords):
            raise ConfigError(f"filters.{key} 必须是非空字符串组成的列表")
    notifiers = _mapping(config.setdefault("notifiers", {}), "notifiers")
    for name, settings in notifiers.items():
        settings = _mapping(settings, f"notifiers.{name}")
        _enabled(settings, f"notifiers.{name}")
        if not settings.get("enabled", True):
            continue
        if name == "wecom":
            validate_wecom(settings)
            continue
        if name != "feishu":
            raise ConfigError(f"V0.1 尚未实现通知器：{name}，请设置 enabled: false")
        webhook = settings.get("webhook_url", "")
        if not isinstance(webhook, str) or (webhook.strip() and not _http_url(webhook.strip())):
            raise ConfigError("飞书 webhook_url 必须留空或填写有效 HTTP(S) URL")
    return config
