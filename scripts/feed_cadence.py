"""Cadence analysis: python -m scripts.feed_cadence [--days 90]

For each enabled RSS source, estimates publishing frequency from what the feed
currently exposes. Feeds only hold their latest N items, so if the oldest item
is newer than the window, the true window rate is higher than shown and the
result is flagged as TRUNCATED (rate is computed over the observed span instead).
"""
from __future__ import annotations

import argparse
import statistics
import time
from datetime import datetime, timezone

import feedparser
import requests

from src.config import load_registry
from src.parser import USER_AGENT


def analyse(source, days: int) -> dict:
    url = source.feed_url or source.url
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    r.raise_for_status()
    parsed = feedparser.parse(r.content)
    ts = sorted(
        calendar_ts(e.get("published_parsed") or e.get("updated_parsed"))
        for e in parsed.entries
        if (e.get("published_parsed") or e.get("updated_parsed"))
    )
    now = time.time()
    cutoff = now - days * 86400
    in_window = [t for t in ts if t >= cutoff]
    out = {"id": source.id, "course": source.course, "items": len(ts), "window": len(in_window)}
    if not ts:
        return out
    out["oldest"] = datetime.fromtimestamp(ts[0], timezone.utc).date().isoformat()
    out["newest"] = datetime.fromtimestamp(ts[-1], timezone.utc).date().isoformat()
    out["truncated"] = ts[0] > cutoff
    span_days = max((now - max(ts[0], cutoff)) / 86400, 1)
    out["per_week"] = round(len(in_window) / span_days * 7, 1)
    out["days_since_last"] = round((now - ts[-1]) / 86400, 1)
    gaps = [(b - a) / 86400 for a, b in zip(ts, ts[1:])]
    out["median_gap_d"] = round(statistics.median(gaps), 1) if gaps else None
    out["max_gap_d"] = round(max(gaps), 1) if gaps else None
    return out


def calendar_ts(st) -> float:
    import calendar
    return float(calendar.timegm(st))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()
    rows = []
    for s in load_registry():
        if s.type != "rss":
            continue
        try:
            rows.append(analyse(s, args.days))
        except Exception as exc:
            print(f"{s.id}: FAILED {exc}")
    print(f"\nWindow: last {args.days} days\n")
    print(f"{'source':<22}{'course':<9}{'in feed':<8}{'in win':<7}{'oldest':<12}{'/week':<7}{'med gap':<9}{'max gap':<9}{'last (d ago)':<13}note")
    total = 0.0
    for r in rows:
        total += r.get("per_week", 0)
        note = "TRUNCATED (feed too shallow)" if r.get("truncated") else ""
        print(f"{r['id']:<22}{r['course']:<9}{r['items']:<8}{r['window']:<7}{r.get('oldest', '-'):<12}"
              f"{r.get('per_week', '-')!s:<7}{r.get('median_gap_d', '-')!s:<9}{r.get('max_gap_d', '-')!s:<9}"
              f"{r.get('days_since_last', '-')!s:<13}{note}")
    print(f"\nCombined estimate: ~{total:.0f} items/week (~{total / 7:.0f}/day) across {len(rows)} sources")


if __name__ == "__main__":
    main()
