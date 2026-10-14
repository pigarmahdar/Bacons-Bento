"""Feed fetching and entry sanitization."""
from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

import feedparser
import requests
from bs4 import BeautifulSoup

from .config import Feed
from .db import entry_id

log = logging.getLogger(__name__)

USER_AGENT = "BaconsBento/1.0 (+https://t.me/baconbento)"
SUMMARY_MAX = 280


@dataclass
class Entry:
    id: str
    feed_url: str
    source_tag: str
    title: str
    link: str
    summary: str
    published: float  # unix timestamp, 0 if unknown
    source_name: str = ""
    course: str = "anchor"


def clean_text(html: str, limit: int = SUMMARY_MAX) -> str:
    text = BeautifulSoup(html or "", "html.parser").get_text(" ")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return cut + "…"


def _summary(e) -> str:
    text = clean_text(e.get("summary", ""))
    # hnrss.org summaries are just "Article URL / Comments URL / Points" boilerplate
    if "Comments URL:" in text:
        return ""
    return text


def parse_feed_bytes(content: bytes, feed: Feed) -> List[Entry]:
    parsed = feedparser.parse(content)
    entries = []
    for e in parsed.entries:
        link = e.get("link")
        title = clean_text(e.get("title", ""), 200)
        if not link or not title:
            continue
        ts = e.get("published_parsed") or e.get("updated_parsed")
        entries.append(
            Entry(
                id=entry_id(e.get("id"), link),
                feed_url=feed.url,
                source_tag=feed.tag,
                title=title,
                link=link,
                summary=_summary(e),
                published=float(calendar.timegm(ts)) if ts else 0.0,
                source_name=feed.name,
                course=feed.course,
            )
        )
    return entries


def fetch_feed(feed: Feed, session: Optional[requests.Session] = None) -> List[Entry]:
    """Fetch one feed. Returns [] (and logs) on any failure."""
    sess = session or requests
    try:
        resp = sess.get(feed.url, headers={"User-Agent": USER_AGENT}, timeout=15)
        resp.raise_for_status()
        return parse_feed_bytes(resp.content, feed)
    except Exception as exc:  # one bad feed must not abort the run
        log.warning("Feed failed (%s): %s", feed.name, exc)
        return []
