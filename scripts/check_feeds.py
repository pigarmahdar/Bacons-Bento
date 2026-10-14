"""Feed health audit: python -m scripts.check_feeds [--all]

Fetches every RSS source in config/registry.yaml and reports HTTP status,
entry count, latest entry date, and paywall hints. Read-only: touches no DB
and posts nothing.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

import feedparser
import requests

from src.config import load_registry
from src.parser import USER_AGENT

PAYWALL_HINTS = ("subscribe to read", "subscribers only", "paywall", "members only", "sign in to read")


def check(source) -> dict:
    url = source.feed_url or source.url
    res = {"id": source.id, "url": url, "status": None, "entries": 0,
           "latest": None, "paywall": False, "ok": False, "note": ""}
    try:
        t0 = time.time()
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        res["status"] = r.status_code
        res["ms"] = int((time.time() - t0) * 1000)
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
        res["entries"] = len(parsed.entries)
        stamps = [e.get("published_parsed") or e.get("updated_parsed") for e in parsed.entries]
        stamps = [s for s in stamps if s]
        if stamps:
            res["latest"] = datetime(*max(stamps)[:6], tzinfo=timezone.utc).date().isoformat()
        blob = " ".join((e.get("summary", "") or "").lower() for e in parsed.entries[:10])
        res["paywall"] = any(h in blob for h in PAYWALL_HINTS)
        if parsed.bozo and not parsed.entries:
            res["note"] = f"unparseable: {parsed.bozo_exception}"
        elif not parsed.entries:
            res["note"] = "no entries"
        else:
            res["ok"] = True
    except Exception as exc:
        res["note"] = str(exc)[:80]
    return res


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    sources = [s for s in load_registry() if s.type == "rss"]
    bad = 0
    print(f"{'source':<22}{'status':<8}{'items':<7}{'latest':<12}{'flags'}")
    for s in sources:
        r = check(s)
        flags = []
        if r["paywall"]:
            flags.append("PAYWALL?")
        if r["note"]:
            flags.append(r["note"])
        mark = "✅" if r["ok"] else "❌"
        bad += not r["ok"]
        print(f"{mark} {r['id']:<20}{str(r['status']):<8}{r['entries']:<7}{str(r['latest']):<12}{' '.join(flags)}")
    print(f"\n{len(sources) - bad}/{len(sources)} healthy")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
