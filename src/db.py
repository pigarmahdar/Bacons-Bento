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

CREATE TABLE IF NOT EXISTS seen_met (
    object_id INTEGER PRIMARY KEY,
    title     TEXT,
    seen_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS drafts (
    issue_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status       TEXT NOT NULL DEFAULT 'pending',
    payload_json TEXT NOT NULL
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
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
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

    def is_met_seen(self, oid: int) -> bool:
        row = self.conn.execute("SELECT 1 FROM seen_met WHERE object_id = ?", (oid,)).fetchone()
        return row is not None

    def mark_met_seen(self, oid: int, title: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_met (object_id, title) VALUES (?,?)",
            (oid, title),
        )
        self.conn.commit()

    def save_draft(self, payload: dict) -> int:
        import json
        cur = self.conn.execute(
            "INSERT INTO drafts (payload_json) VALUES (?)",
            (json.dumps(payload),),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_draft(self, issue_id: Optional[int] = None) -> Optional[dict]:
        import json
        if issue_id is not None:
            row = self.conn.execute(
                "SELECT issue_id, created_at, status, payload_json FROM drafts WHERE issue_id = ?",
                (issue_id,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT issue_id, created_at, status, payload_json FROM drafts WHERE status = 'pending' ORDER BY issue_id DESC LIMIT 1"
            ).fetchone()

        if not row:
            return None
        payload = json.loads(row["payload_json"])
        payload["issue_id"] = row["issue_id"]
        payload["created_at"] = row["created_at"]
        payload["status"] = row["status"]
        return payload

    def approve_draft(self, issue_id: int) -> Optional[dict]:
        draft = self.get_draft(issue_id)
        if not draft:
            return None
        self.conn.execute(
            "UPDATE drafts SET status = 'approved' WHERE issue_id = ?",
            (issue_id,),
        )
        self.conn.commit()
        draft["status"] = "approved"
        return draft

    def reject_draft(self, issue_id: int) -> bool:
        cur = self.conn.execute(
            "UPDATE drafts SET status = 'rejected' WHERE issue_id = ?",
            (issue_id,),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def prune(self, days: int = 180) -> int:
        cur = self.conn.execute(
            "DELETE FROM seen WHERE first_seen < datetime('now', ?)", (f"-{int(days)} days",)
        )
        self.conn.commit()
        return cur.rowcount

    def get_hopper_stats(self) -> dict:
        import json
        seen_total = self.conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
        posted_total = self.conn.execute("SELECT COUNT(*) FROM seen WHERE posted = 1").fetchone()[0]
        met_seen_total = self.conn.execute("SELECT COUNT(*) FROM seen_met").fetchone()[0]
        published_count = self.conn.execute("SELECT COUNT(*) FROM drafts WHERE status = 'approved'").fetchone()[0]
        
        pending_draft = self.get_draft()

        last_published = None
        last_pub_row = self.conn.execute(
            "SELECT issue_id, created_at, status, payload_json FROM drafts WHERE status = 'approved' ORDER BY issue_id DESC LIMIT 1"
        ).fetchone()
        if last_pub_row:
            last_published = json.loads(last_pub_row["payload_json"])
            last_published["issue_id"] = last_pub_row["issue_id"]
            last_published["created_at"] = last_pub_row["created_at"]
            last_published["status"] = last_pub_row["status"]

        return {
            "seen_total": seen_total,
            "posted_total": posted_total,
            "met_seen_total": met_seen_total,
            "published_count": published_count,
            "pending_draft": pending_draft,
            "last_published": last_published,
        }

    def close(self) -> None:
        self.conn.close()


