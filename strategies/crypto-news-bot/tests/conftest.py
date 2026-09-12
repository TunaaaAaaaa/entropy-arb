import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    original = requests.sessions.Session.request

    def guarded(self, method, url, *args, **kwargs):
        from urllib.parse import urlsplit
        if urlsplit(url).hostname != "127.0.0.1":
            raise AssertionError("Tests must not contact real RSS feeds or chat groups")
        return original(self, method, url, *args, **kwargs)

    monkeypatch.setattr(requests.sessions.Session, "request", guarded)
