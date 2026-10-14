"""SQLite persistence for deduplication."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"fbclid", "gclid", "ref", "ref_src", "mc_cid", "mc_eid"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    entry_id   TEXT PRIMARY KEY,
    feed_url   TEXT,
    title      TEXT,
    link       TEXT,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    posted     INTEGER NOT NULL DEFAULT 0
);
"""


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_KEYS and not k.lower().startswith(TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def entry_id(guid: Optional[str], link: str) -> str:
    key = guid or normalize_url(link)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def is_seen(self, eid: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM seen WHERE entry_id = ?", (eid,)).fetchone()
        return row is not None

    def mark_seen(self, eid: str, feed_url: str, title: str, link: str, posted: bool) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen (entry_id, feed_url, title, link, posted) VALUES (?,?,?,?,?)",
            (eid, feed_url, title, link, int(posted)),
        )
        self.conn.commit()

    def prune(self, days: int = 180) -> int:
        cur = self.conn.execute(
            "DELETE FROM seen WHERE first_seen < datetime('now', ?)", (f"-{int(days)} days",)
        )
        self.conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self.conn.close()
