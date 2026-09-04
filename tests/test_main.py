"""Entry-point signal handling.

Run:  python3 -m pytest tests/  (or  python3 tests/test_main.py)
"""
import os
import signal
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main as app  # noqa: E402


class SupportedSignalLoop:
    def __init__(self):
        self.handlers = []
        self.removed = []

    def add_signal_handler(self, sig, callback):
        self.handlers.append((sig, callback))

    def remove_signal_handler(self, sig):
        self.removed.append(sig)


class UnsupportedSignalLoop(SupportedSignalLoop):
    def __init__(self):
        super().__init__()
        self.scheduled = []

    def add_signal_handler(self, sig, callback):
        self.handlers.append((sig, callback))
        raise NotImplementedError()

    def call_soon_threadsafe(self, callback):
        self.scheduled.append(callback)


def test_supported_loop_uses_asyncio_signal_handlers():
    loop = SupportedSignalLoop()
    callback = lambda: None
    old_handlers = {signal.SIGINT: object(), signal.SIGTERM: object()}

    def fake_getsignal(sig):
        return old_handlers[sig]

    with patch.object(app.signal, "getsignal", side_effect=fake_getsignal):
        with patch.object(app.signal, "signal") as restore:
            with app._signal_handlers(loop, callback):
                pass

    assert [sig for sig, _callback in loop.handlers] == [
        signal.SIGINT, signal.SIGTERM]
    assert all(installed == callback
               for _sig, installed in loop.handlers)
    assert loop.removed == [signal.SIGINT, signal.SIGTERM]
    assert [call.args for call in restore.call_args_list] == [
        (signal.SIGINT, old_handlers[signal.SIGINT]),
        (signal.SIGTERM, old_handlers[signal.SIGTERM])]


def test_unsupported_loop_falls_back_and_restores_handlers():
    loop = UnsupportedSignalLoop()
    callback = lambda: None
    old_handlers = {signal.SIGINT: object(), signal.SIGTERM: object()}
    calls = []

    def fake_signal(sig, handler):
        calls.append((sig, handler))

    with patch.object(app.signal, "getsignal",
                      side_effect=lambda sig: old_handlers[sig]):
        with patch.object(app.signal, "signal", side_effect=fake_signal):
            with app._signal_handlers(loop, callback):
                installed = calls[0][1]
                installed(signal.SIGINT, None)

    assert loop.scheduled == [callback]
    assert calls[2:] == [
        (signal.SIGINT, old_handlers[signal.SIGINT]),
        (signal.SIGTERM, old_handlers[signal.SIGTERM])]


def test_fallback_handlers_are_restored_after_error():
    loop = UnsupportedSignalLoop()
    old_handlers = {signal.SIGINT: object(), signal.SIGTERM: object()}
    calls = []

    def fake_signal(sig, handler):
        calls.append((sig, handler))

    try:
        with patch.object(app.signal, "getsignal",
                          side_effect=lambda sig: old_handlers[sig]):
            with patch.object(app.signal, "signal", side_effect=fake_signal):
                with app._signal_handlers(loop, lambda: None):
                    raise RuntimeError("boom")
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected RuntimeError")

    assert calls[2:] == [
        (signal.SIGINT, old_handlers[signal.SIGINT]),
        (signal.SIGTERM, old_handlers[signal.SIGTERM])]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"{name:55s} OK")
