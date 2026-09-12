"""WeCom aibot WebSocket protocol: subscribe, JSON ping and proactive send.

One receiver thread owns authentication and heartbeat. Sends wait for a matching
business acknowledgement; disconnected or timed-out sends aren't replayed here.
"""
import hashlib
import json
import logging
import threading
import time
import uuid

from .base import BaseNotifier

logger = logging.getLogger(__name__)


class WeComNotifier(BaseNotifier):
    def __init__(self, bot_id, secret, chat_id="", *, ws_url="wss://openws.work.weixin.qq.com",
                 timeout_seconds=10, heartbeat_seconds=30, reconnect_seconds=1):
        self.bot_id = bot_id.strip()
        self.secret = secret.strip()
        self.chat_id = chat_id.strip()
        self.ws_url = ws_url
        self.timeout = timeout_seconds
        self.heartbeat = heartbeat_seconds
        self.reconnect = reconnect_seconds
        identity = json.dumps([self.bot_id, self.chat_id], separators=(",", ":"))
        self.delivery_key = "wecom:" + hashlib.sha256(identity.encode()).hexdigest()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._auth_failed = threading.Event()
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._thread = None
        self._ws = None
        self._pending = {}
        self._groups = set()

    def start(self):
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="wecom-connection", daemon=True)
                self._thread.start()

    def wait_ready(self, timeout=None):
        self.start()
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while not self._stop.is_set() and not self._auth_failed.is_set():
            if self._ready.wait(min(0.1, max(0, deadline - time.monotonic()))):
                return True
            if time.monotonic() >= deadline:
                break
        return False

    @staticmethod
    def _frame(cmd, body=None):
        frame = {"cmd": cmd, "headers": {"req_id": f"{cmd}_{uuid.uuid4().hex}"}}
        if body is not None:
            frame["body"] = body
        return frame

    @staticmethod
    def _success(frame):
        return type(frame.get("errcode")) is int and frame["errcode"] == 0

    def _write(self, ws, frame):
        with self._send_lock:
            ws.send(json.dumps(frame, ensure_ascii=False))

    def _on_callback(self, frame):
        # Discovery only: never auto-subscribe or reply to an incoming message.
        body = frame.get("body", {})
        if isinstance(body, dict) and body.get("chattype") == "group":
            chat_id = body.get("chatid")
            if isinstance(chat_id, str) and chat_id:
                with self._lock:
                    self._groups.add(chat_id)

    def discovered_groups(self):
        with self._lock:
            return sorted(self._groups)

    def _fail_pending(self):
        with self._lock:
            for request in self._pending.values():
                request["done"].set()
            self._pending.clear()

    def _run(self):
        from websockets.sync.client import connect

        # The transport's debug frames can contain authentication secrets.
        transport_logger = logging.Logger("wecom.transport", level=logging.CRITICAL + 1)
        transport_logger.addHandler(logging.NullHandler())
        delay = self.reconnect
        while not self._stop.is_set():
            try:
                with connect(self.ws_url, open_timeout=self.timeout, close_timeout=1,
                             ping_interval=None, max_size=1024 * 1024, logger=transport_logger) as ws:
                    with self._lock:
                        self._ws = ws
                    auth = self._frame("aibot_subscribe", {"bot_id": self.bot_id, "secret": self.secret})
                    auth_id = auth["headers"]["req_id"]
                    self._write(ws, auth)
                    auth_deadline = time.monotonic() + self.timeout
                    next_ping = 0
                    ping_id = None
                    ping_deadline = 0
                    while not self._stop.is_set():
                        now = time.monotonic()
                        if not self._ready.is_set() and now >= auth_deadline:
                            raise TimeoutError()
                        if self._ready.is_set():
                            if ping_id and now >= ping_deadline:
                                raise TimeoutError()
                            if not ping_id and now >= next_ping:
                                ping = self._frame("ping")
                                ping_id = ping["headers"]["req_id"]
                                ping_deadline = now + self.timeout
                                self._write(ws, ping)
                        try:
                            frame = json.loads(ws.recv(timeout=0.1))
                        except TimeoutError:
                            continue
                        except (ValueError, UnicodeError):
                            logger.warning("企业微信收到无法解析的帧，已忽略")
                            continue
                        if not isinstance(frame, dict) or not isinstance(frame.get("headers"), dict):
                            continue
                        req_id = frame["headers"].get("req_id")
                        if not isinstance(req_id, str):
                            continue
                        if frame.get("cmd") in ("aibot_msg_callback", "aibot_event_callback"):
                            self._on_callback(frame)
                        elif req_id == auth_id:
                            if not self._success(frame):
                                self._auth_failed.set()
                                logger.error("企业微信认证被拒绝，请检查 Bot ID 和 Secret")
                                return
                            self._ready.set()
                            next_ping = time.monotonic() + self.heartbeat
                            delay = self.reconnect
                            logger.info("企业微信长连接认证成功")
                        elif ping_id and req_id == ping_id:
                            if not self._success(frame):
                                raise ConnectionError()
                            ping_id = None
                            next_ping = time.monotonic() + self.heartbeat
                        else:
                            with self._lock:
                                request = self._pending.pop(req_id, None)
                                if request:
                                    request["success"] = self._success(frame)
                                    request["done"].set()
            except Exception as exc:
                if not self._stop.is_set():
                    logger.warning("企业微信连接中断（%s），将重新连接", type(exc).__name__)
            finally:
                self._ready.clear()
                with self._lock:
                    self._ws = None
                self._fail_pending()
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, 30)

    def send(self, message: str) -> bool:
        if not self.chat_id:
            logger.error("企业微信未配置目标群 chat_id，无法主动推送")
            return False
        if not self.wait_ready():
            logger.error("企业微信尚未认证连接，未发送新闻")
            return False
        # WeCom proactive send accepts markdown. Keep the payload under 4096 bytes.
        content = message
        if len(content.encode("utf-8")) > 4000:
            # Preserve the original news link at the end of the message.
            head, separator, tail = content.rpartition("\n链接：")
            suffix = separator + tail if separator else ""
            available = max(0, 3990 - len(suffix.encode("utf-8")))
            if len(suffix.encode("utf-8")) > 3000:
                logger.error("企业微信消息链接过长，无法完整发送")
                return False
            content = (head if separator else content).encode("utf-8")[:available].decode("utf-8", errors="ignore") + "…" + suffix
        frame = self._frame("aibot_send_msg", {"chatid": self.chat_id, "msgtype": "markdown", "markdown": {"content": content}})
        req_id = frame["headers"]["req_id"]
        request = {"done": threading.Event(), "success": False}
        with self._lock:
            ws = self._ws
            if ws is None or not self._ready.is_set():
                return False
            self._pending[req_id] = request
        try:
            self._write(ws, frame)
            request["done"].wait(self.timeout)
            if request["success"]:
                return True
            logger.error("企业微信未确认消息发送成功；本轮不自动重发")
        except Exception as exc:
            logger.error("企业微信发送失败（%s）", type(exc).__name__)
        finally:
            with self._lock:
                self._pending.pop(req_id, None)
        return False

    def close(self):
        self._stop.set()
        self._ready.clear()
        with self._lock:
            ws = self._ws
        if ws is not None:
            ws.close()
        self._fail_pending()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=self.timeout + 2)
