"""Core orchestration pipeline: python -m src.main [--draft] [--approve [ID]] [--bootstrap] [--dry-run]"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from .config import load_feeds, load_registry, load_settings
from .curator import curate_candidates
from .db import Database
from .drafter import draft_issue_package
from .llm import OpenRouterClient
from .met import MetArtwork, fetch_met_artwork
from .pantry import collect_candidates
from .parser import Entry, fetch_feed
from .telegram import TelegramClient, TelegramError

log = logging.getLogger("bento")


def run_bootstrap(db: Database) -> int:
    feeds = load_feeds()
    recorded = 0
    for feed in feeds:
        for entry in fetch_feed(feed):
            if not db.is_seen(entry.id):
                db.mark_seen(entry.id, entry.feed_url, entry.title, entry.link, posted=False)
                recorded += 1
    log.info("Bootstrap complete: recorded %d entries without posting", recorded)
    return 0


def run_draft(dry_run: bool = False) -> int:
    settings = load_settings(require_telegram=False)
    feeds = load_feeds()
    db = Database(settings.db_path)

    # 1. Collect unseen candidate pool (RSS Feeds + Chef's Pantry)
    candidates, breakdown = collect_candidates(feeds, settings, db, dry_run=dry_run)
    log.info(
        "Ingested %d unseen candidate articles across %d feeds (RSS: %d, Obsidian: %d, Telegram: %d)",
        len(candidates),
        len(feeds),
        breakdown["rss"],
        breakdown["obsidian"],
        breakdown["telegram"],
    )

    # 2. Fetch Course 5: The Met Open Access Artwork
    met_source = next((s for s in load_registry() if s.id == "met-collection"), None)
    met_art = None
    if met_source and met_source.enabled:
        met_art = fetch_met_artwork(met_source, is_seen=db.is_met_seen)
        if met_art:
            log.info("Selected Met artwork: '%s' by %s", met_art.title, met_art.artist)

    # 3. Decision Model evaluation
    if not settings.openrouter_api_key:
        log.error("OPENROUTER_API_KEY is required for curation drafting.")
        return 1

    llm_client = OpenRouterClient(
        api_key=settings.openrouter_api_key,
        default_model=settings.openrouter_decision_model,
    )

    log.info("Running Decision Model (%s)...", settings.openrouter_decision_model)
    curation = curate_candidates(candidates, llm_client, model=settings.openrouter_decision_model)

    # 4. Determine next issue number
    # Count how many approved drafts exist in DB + 1
    cur = db.conn.execute("SELECT COUNT(*) FROM drafts WHERE status = 'approved'")
    issue_number = cur.fetchone()[0] + 1

    # 5. Drafter Model synthesis
    log.info("Drafting sentence package with model (%s)...", settings.openrouter_drafting_model)
    package = draft_issue_package(
        curation=curation,
        met_artwork=met_art,
        issue_number=issue_number,
        client=llm_client,
        model=settings.openrouter_drafting_model,
    )

    if dry_run:
        print("\n" + "=" * 50)
        print("🍱 DRY RUN REVIEW SUMMARY (Private Admin):")
        print("=" * 50)
        print(package.review_summary_html)
        print("\n" + "=" * 50)
        print("PUBLIC ISSUE PREVIEW:")
        print("=" * 50)
        print(package.issue_html)
        if package.met_artwork:
            print(f"\n[Artwork Photo URL: {package.met_artwork.image_url}]")
        db.close()
        return 0

    # 6. Save draft in database
    draft_payload = {
        "issue_number": issue_number,
        "issue_html": package.issue_html,
        "selected_entries": [
            {
                "id": e.id,
                "feed_url": e.feed_url,
                "title": e.title,
                "link": e.link,
                "course": e.course,
                "source": e.source_name,
            }
            for e in curation.selected_entries
        ],
        "met_artwork": (
            {
                "object_id": met_art.object_id,
                "title": met_art.title,
                "artist": met_art.artist,
                "date": met_art.date,
                "medium": met_art.medium,
                "object_url": met_art.object_url,
                "image_url": met_art.image_url,
                "department": met_art.department,
            }
            if met_art
            else None
        ),
    }

    draft_id = db.save_draft(draft_payload)
    log.info("Draft saved to database as Issue #%d (Draft ID: %d)", issue_number, draft_id)

    # 7. Send review preview to Bacon's private Telegram chat
    if settings.bot_token and settings.admin_chat_id:
        tg = TelegramClient(settings.bot_token, settings.admin_chat_id)
        try:
            tg.send(package.review_summary_html, chat_id=settings.admin_chat_id)
            if package.met_artwork:
                met = package.met_artwork
                caption = (
                    f"🌳 <b>{met.title}</b> ({met.date or 'n.d.'})\n"
                    f"<i>{met.artist or 'Unknown Artist'}</i> · {met.medium}\n"
                    f"{met.department}, <a href=\"{met.object_url}\">The Met Collection (CC0)</a>"
                )
                tg.send_photo(met.image_url, caption=caption, chat_id=settings.admin_chat_id)
            log.info("Dispatched draft review to private admin chat (%s)", settings.admin_chat_id)
        except TelegramError as exc:
            log.error("Failed to send review preview to Telegram: %s", exc)

    db.close()
    return 0


def run_approve(issue_id: Optional[int] = None) -> int:
    settings = load_settings(require_telegram=True)
    db = Database(settings.db_path)
    draft = db.get_draft(issue_id)

    if not draft:
        log.error("No pending draft found%s", f" for issue_id={issue_id}" if issue_id else "")
        db.close()
        return 1

    issue_html = draft.get("issue_html")
    if not issue_html:
        log.error("Draft payload missing 'issue_html'")
        db.close()
        return 1

    tg = TelegramClient(settings.bot_token, settings.chat_id)
    log.info("Publishing Issue #%d to %s...", draft.get("issue_number", 1), settings.chat_id)

    # 1. Send the unified issue text
    try:
        tg.send(issue_html, chat_id=settings.chat_id)
    except TelegramError as exc:
        log.error("Failed to publish issue text to Telegram: %s", exc)
        db.close()
        return 1

    # 2. Send the Met artwork photo if present
    met_data = draft.get("met_artwork")
    if met_data and met_data.get("image_url"):
        caption = (
            f"🌳 <b>{met_data.get('title')}</b> ({met_data.get('date') or 'n.d.'})\n"
            f"<i>{met_data.get('artist') or 'Unknown Artist'}</i> · {met_data.get('medium') or ''}\n"
            f"{met_data.get('department')}, <a href=\"{met_data.get('object_url')}\">The Met Collection (CC0)</a>"
        )
        try:
            tg.send_photo(met_data["image_url"], caption=caption, chat_id=settings.chat_id)
            db.mark_met_seen(met_data["object_id"], met_data.get("title", ""))
        except TelegramError as exc:
            log.warning("Issue posted, but failed to post Met artwork: %s", exc)

    # 3. Mark selected entries as seen/posted in database
    for e in draft.get("selected_entries", []):
        db.mark_seen(e["id"], e.get("feed_url", ""), e.get("title", ""), e.get("link", ""), posted=True)

    # 4. Mark draft as approved
    db.approve_draft(draft["issue_id"])
    log.info("✅ Issue #%d successfully approved and published!", draft.get("issue_number", 1))

    # Notify admin
    if settings.admin_chat_id:
        try:
            tg.send(f"✅ <b>Issue #{draft.get('issue_number')} has been published to {settings.chat_id}!</b>", chat_id=settings.admin_chat_id)
        except Exception:
            pass

    db.close()
    return 0


def main() -> None:
    # If a CLI subcommand is passed, route directly to cli.main
    subcommands = {"new", "draft", "preview", "show", "publish", "approve", "status", "bootstrap"}
    if len(sys.argv) > 1 and sys.argv[1] in subcommands:
        from . import cli
        sys.exit(cli.main(sys.argv[1:]))

    ap = argparse.ArgumentParser(description="Bacon's Bento Orchestration Pipeline")
    ap.add_argument("--draft", action="store_true", help="run Curation & Drafter models, generate weekly draft, send to admin chat")
    ap.add_argument("--approve", nargs="?", const=-1, type=int, help="approve and publish pending draft (optionally specify issue ID)")
    ap.add_argument("--bootstrap", action="store_true", help="record current feed entries without posting")
    ap.add_argument("--dry-run", action="store_true", help="simulate draft generation and print output without saving or sending")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.bootstrap:
        settings = load_settings(require_telegram=False)
        db = Database(settings.db_path)
        sys.exit(run_bootstrap(db))

    if args.approve is not None:
        issue_id = None if args.approve == -1 else args.approve
        sys.exit(run_approve(issue_id))

    # Default action or --draft (or --dry-run)
    sys.exit(run_draft(dry_run=args.dry_run))


if __name__ == "__main__":
    main()

