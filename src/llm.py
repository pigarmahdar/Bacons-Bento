"""OpenRouter API client for Curation and Drafting models."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_DECISIONS_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"


class LLMError(Exception):
    pass


class OpenRouterClient:
    def __init__(self, api_key: str, default_model: str = "xiaomi/mimo-v2.6-flash", timeout: int = 45):
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY must be provided")
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout

    def decide(
        self,
        state: str,
        questions: Dict[str, Any],
        model: str = "typesafe/jev-1.13",
        max_attempts: int = 3,
    ) -> Dict[str, Any]:
        """Call OpenRouter Decisions API (e.g. typesafe/jev-1.13)."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://t.me/baconbento",
            "X-Title": "Bacons Bento Curation Engine",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "state": state,
            "questions": questions,
        }
        last_err = None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = requests.post(OPENROUTER_DECISIONS_ENDPOINT, headers=headers, json=payload, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("answers", {})
                if resp.status_code in (429, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(f"OpenRouter Decisions HTTP {resp.status_code}: {resp.text[:300]}")
            except (requests.RequestException, KeyError) as exc:
                last_err = exc
                time.sleep(2 ** attempt)
        raise LLMError(f"OpenRouter Decisions call failed after {max_attempts} attempts: {last_err}")

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        json_mode: bool = False,
        max_attempts: int = 3,
    ) -> str:
        target_model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://t.me/baconbento",
            "X-Title": "Bacons Bento Curation Engine",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_err = None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = requests.post(OPENROUTER_ENDPOINT, headers=headers, json=payload, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices")
                    if not choices:
                        raise LLMError(f"No choices returned by {target_model}: {data}")
                    return choices[0]["message"]["content"]
                
                if resp.status_code in (429, 502, 503, 504):
                    retry_wait = 2 ** attempt
                    log.warning("OpenRouter %d on attempt %d; sleeping %ds", resp.status_code, attempt, retry_wait)
                    time.sleep(retry_wait)
                    continue

                raise LLMError(f"OpenRouter HTTP {resp.status_code}: {resp.text[:300]}")
            except (requests.RequestException, KeyError) as exc:
                last_err = exc
                log.warning("OpenRouter call failed (attempt %d): %s", attempt, exc)
                time.sleep(2 ** attempt)

        raise LLMError(f"OpenRouter call failed after {max_attempts} attempts: {last_err}")
