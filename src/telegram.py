"""Telegram Bot API client with retry and rate-limit handling."""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(self, token: str, chat_id: str, min_interval: float = 1.0, max_attempts: int = 3):
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self._last_sent = 0.0

    def send(self, text: str) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_sent)
        if wait > 0:
            time.sleep(wait)
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = requests.post(self._url, json=payload, timeout=15)
            except requests.RequestException as exc:
                err = f"network error: {type(exc).__name__}"
                if attempt == self.max_attempts:
                    raise TelegramError(err) from None
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 200:
                self._last_sent = time.monotonic()
                return
            if resp.status_code == 429:
                retry_after = 5
                try:
                    retry_after = int(resp.json()["parameters"]["retry_after"])
                except Exception:
                    pass
                time.sleep(retry_after)
                continue
            if resp.status_code >= 500 and attempt < self.max_attempts:
                time.sleep(2 ** attempt)
                continue
            # 4xx or exhausted 5xx. Never include the URL (it contains the token).
            raise TelegramError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        raise TelegramError("exhausted retries")
