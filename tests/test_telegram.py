import pytest

from src import telegram
from src.telegram import TelegramClient, TelegramError


class Resp:
    def __init__(self, code, body=None, text=""):
        self.status_code, self._body, self.text = code, body or {}, text

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(telegram.time, "sleep", lambda s: None)


def client():
    return TelegramClient("TOKEN", "@chan", min_interval=0)


def patch_post(monkeypatch, responses):
    calls = iter(responses)
    seen = []

    def fake(url, json=None, timeout=None):
        seen.append(json)
        return next(calls)

    monkeypatch.setattr(telegram.requests, "post", fake)
    return seen


def test_success(monkeypatch):
    seen = patch_post(monkeypatch, [Resp(200)])
    client().send("hi")
    assert seen[0]["parse_mode"] == "HTML" and seen[0]["chat_id"] == "@chan"


def test_429_then_ok(monkeypatch):
    patch_post(monkeypatch, [Resp(429, {"parameters": {"retry_after": 1}}), Resp(200)])
    client().send("hi")


def test_5xx_then_ok(monkeypatch):
    patch_post(monkeypatch, [Resp(502), Resp(200)])
    client().send("hi")


def test_hard_failure_hides_token(monkeypatch):
    patch_post(monkeypatch, [Resp(400, text="bad request")])
    with pytest.raises(TelegramError) as ei:
        client().send("hi")
    assert "TOKEN" not in str(ei.value)
