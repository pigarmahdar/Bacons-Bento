"""Env var loading, source registry, and feed list validation."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class TasteProfile:
    cognitive_load: str = "engaged"
    cadence: str = "weekly"
    tone: str = "contemplative"


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    type: str  # "rss" | "api"
    url: str
    feed_url: str = ""
    endpoint: str = ""
    course: str = "anchor"
    curatorial_sensibility: str = ""
    pillars: List[str] = field(default_factory=list)
    taste_profile: TasteProfile = field(default_factory=TasteProfile)
    tag: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    tag: str
    course: str = "anchor"
    source_id: str = ""
    curatorial_sensibility: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class Settings:
    bot_token: str
    chat_id: str
    admin_chat_id: str
    openrouter_api_key: str
    openrouter_decision_model: str
    openrouter_drafting_model: str
    db_path: str
    max_posts_per_run: int
    obsidian_clippings_path: str = ""
    bento_issues_path: str = ""
    pantry_max_age_days: int = 30


def load_settings(require_telegram: bool = True) -> Settings:
    load_dotenv(ROOT / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if require_telegram and (not token or not chat_id):
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
    return Settings(
        bot_token=token,
        chat_id=chat_id,
        admin_chat_id=os.getenv("TELEGRAM_ADMIN_CHAT_ID", ""),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openrouter_decision_model=os.getenv("OPENROUTER_DECISION_MODEL", "xiaomi/mimo-v2.6-flash"),
        openrouter_drafting_model=os.getenv("OPENROUTER_DRAFTING_MODEL", "xiaomi/mimo-v2.6-flash"),
        db_path=os.getenv("DB_PATH", str(ROOT / "data" / "bento_history.db")),
        max_posts_per_run=int(os.getenv("MAX_POSTS_PER_RUN", "5")),
        obsidian_clippings_path=os.getenv(
            "OBSIDIAN_CLIPPINGS_PATH",
            os.path.expanduser("~/Documents/Bacon Notes/Clippings"),
        ),
        bento_issues_path=os.getenv(
            "BENTO_ISSUES_PATH",
            os.path.expanduser("~/Documents/Bacon Notes/1. Personal/Github Projects/bacons-bento/Bento Issues"),
        ),
        pantry_max_age_days=int(os.getenv("PANTRY_MAX_AGE_DAYS", "30")),
    )


def load_registry(path: Path | None = None) -> List[Source]:
    """Load the rich editorial source registry from registry.yaml."""
    path = path or ROOT / "config" / "registry.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Registry not found at {path}")
    if yaml is None:
        raise RuntimeError("PyYAML is required to parse registry.yaml")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "sources" not in raw:
        raise ValueError("registry.yaml must contain a top-level 'sources' list")

    sources: List[Source] = []
    for item in raw["sources"]:
        tp_raw = item.get("taste_profile") or {}
        tp = TasteProfile(
            cognitive_load=tp_raw.get("cognitive_load", "engaged"),
            cadence=tp_raw.get("cadence", "weekly"),
            tone=tp_raw.get("tone", "contemplative"),
        )
        source = Source(
            id=item["id"],
            name=item["name"],
            type=item.get("type", "rss"),
            url=item.get("url", ""),
            feed_url=item.get("feed_url", ""),
            endpoint=item.get("endpoint", ""),
            course=item.get("course", "anchor"),
            curatorial_sensibility=item.get("curatorial_sensibility", ""),
            pillars=list(item.get("pillars") or []),
            taste_profile=tp,
            tag=item.get("tag") or item["id"],
            config=dict(item.get("config") or {}),
            enabled=bool(item.get("enabled", True)),
        )
        sources.append(source)
    return [s for s in sources if s.enabled]


def load_feeds(path: Path | None = None) -> List[Feed]:
    """Load RSS feeds for the pipeline from registry.yaml (the single source of truth)."""
    sources = load_registry(Path(path) if path is not None else None)
    return [
        Feed(
            name=s.name,
            url=s.feed_url or s.url,
            tag=s.tag or s.id,
            course=s.course,
            source_id=s.id,
            curatorial_sensibility=s.curatorial_sensibility,
            enabled=s.enabled,
        )
        for s in sources
        if s.type == "rss" and (s.feed_url or s.url)
    ]
