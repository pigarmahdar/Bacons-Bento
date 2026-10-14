"""Core orchestration pipeline: python -m src.main [--bootstrap] [--dry-run]"""
from __future__ import annotations

import argparse
import logging
import sys

from .config import load_feeds, load_settings
from .db import Database
from .formatter import format_entry
from .parser import fetch_feed
from .telegram import TelegramClient, TelegramError

log = logging.getLogger("bento")


def run(bootstrap: bool = False, dry_run: bool = False) -> int:
    settings = load_settings(require_telegram=not (bootstrap or dry_run))
    feeds = load_feeds()
    db = Database(settings.db_path)

    new = []
    batch_ids = set()
    for feed in feeds:
        for entry in fetch_feed(feed):
            if entry.id in batch_ids or db.is_seen(entry.id):
                continue
            batch_ids.add(entry.id)
            new.append(entry)
    log.info("%d new entries from %d feeds", len(new), len(feeds))

    if bootstrap:
        for e in new:
            db.mark_seen(e.id, e.feed_url, e.title, e.link, posted=False)
        log.info("Bootstrap: recorded %d entries without posting", len(new))
        db.close()
        return 0

    # Newest first, keep the top N; the older overflow is recorded as seen
    # (unposted) so a backlog never trickles out stale items on later runs.
    new.sort(key=lambda e: e.published, reverse=True)
    to_post = new[: settings.max_posts_per_run]
    overflow = new[settings.max_posts_per_run :]
    to_post.reverse()  # post oldest-to-newest so the channel reads chronologically

    client = None if dry_run else TelegramClient(settings.bot_token, settings.chat_id)
    failures = 0
    for e in to_post:
        text = format_entry(e)
        if dry_run:
            print(text, end="\n" + "-" * 40 + "\n")
            continue
        try:
            client.send(text)
            db.mark_seen(e.id, e.feed_url, e.title, e.link, posted=True)
            log.info("Posted: %s", e.title)
        except TelegramError as exc:
            failures += 1
            log.error("Send failed for '%s': %s", e.title, exc)

    if not dry_run:
        for e in overflow:
            db.mark_seen(e.id, e.feed_url, e.title, e.link, posted=False)
        db.prune()
    db.close()
    return 1 if failures and failures == len(to_post) else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", action="store_true", help="record current entries without posting")
    ap.add_argument("--dry-run", action="store_true", help="print posts, don't send or record")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(run(bootstrap=args.bootstrap, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
