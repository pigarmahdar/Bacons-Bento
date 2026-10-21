"""Bacon's Bento CLI: intentional, on-demand editorial commands."""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional, Sequence

from .config import load_feeds, load_registry, load_settings
from .curator import curate_candidates
from .db import Database
from .drafter import draft_issue_package
from .formatter import format_terminal_box, html_to_terminal
from .llm import OpenRouterClient
from .met import fetch_met_artwork
from .pantry import collect_candidates
from .parser import fetch_feed
from .telegram import TelegramClient, TelegramError

log = logging.getLogger("bento")


def render_issue_terminal(issue_html: str, met_artwork: Optional[dict] = None) -> None:
    """Print an issue cleanly styled for the terminal."""
    rendered_text = html_to_terminal(issue_html)
    print("\n" + format_terminal_box("🍱 BACON'S BENTO · ISSUE PREVIEW", rendered_text))
    if met_artwork:
        art_info = (
            f"\033[1m{met_artwork.get('title')}\033[0m ({met_artwork.get('date') or 'n.d.'})\n"
            f"\033[3m{met_artwork.get('artist') or 'Unknown Artist'}\033[0m · {met_artwork.get('medium') or ''}\n"
            f"Department: {met_artwork.get('department')}\n"
            f"Image URL: \033[4;36m{met_artwork.get('image_url')}\033[0m\n"
            f"Met Collection: \033[4;36m{met_artwork.get('object_url')}\033[0m"
        )
        print("\n" + format_terminal_box("🖼️  COURSE 5: MET OPEN ACCESS ARTWORK", art_info))


def cmd_new(args: argparse.Namespace) -> int:
    """Draft a new Bento issue."""
    dry_run = getattr(args, "dry_run", False)
    no_notify = getattr(args, "no_notify", False)

    settings = load_settings(require_telegram=False)
    feeds = load_feeds()
    db = Database(settings.db_path)

    print("\033[1m🍱 Bento: Ingesting feeds & assembling candidates...\033[0m")
    candidates, breakdown = collect_candidates(feeds, settings, db, dry_run=dry_run)
    log.info(
        "Ingested %d unseen candidates (RSS: %d, Obsidian: %d, Telegram: %d)",
        breakdown["total"],
        breakdown["rss"],
        breakdown["obsidian"],
        breakdown["telegram"],
    )
    print(
        f"  → Found {breakdown['total']} unseen candidate articles: "
        f"{breakdown['rss']} RSS, {breakdown['obsidian']} Obsidian clippings, {breakdown['telegram']} Telegram drops."
    )

    # 2. Fetch Course 5: The Met Open Access Artwork
    met_source = next((s for s in load_registry() if s.id == "met-collection"), None)
    met_art = None
    if met_source and met_source.enabled:
        print("  → Selecting Course 5: The Met Collection artwork...")
        met_art = fetch_met_artwork(met_source, is_seen=db.is_met_seen)
        if met_art:
            log.info("Selected Met artwork: '%s' by %s", met_art.title, met_art.artist)
            print(f"  → Met Artwork: \"{met_art.title}\" by {met_art.artist or 'Unknown'}")

    # 3. Decision Model evaluation
    if not settings.openrouter_api_key:
        print("\n\033[31mError: OPENROUTER_API_KEY is required for curation drafting.\033[0m", file=sys.stderr)
        db.close()
        return 1

    llm_client = OpenRouterClient(
        api_key=settings.openrouter_api_key,
        default_model=settings.openrouter_decision_model,
    )

    print(f"  → Evaluating candidates with Decision Model ({settings.openrouter_decision_model})...")
    curation = curate_candidates(candidates, llm_client, model=settings.openrouter_decision_model)

    # 4. Next issue number
    cur = db.conn.execute("SELECT COUNT(*) FROM drafts WHERE status = 'approved'")
    issue_number = cur.fetchone()[0] + 1

    # 5. Drafter Model synthesis
    print(f"  → Synthesizing issue with Drafter Model ({settings.openrouter_drafting_model})...")
    package = draft_issue_package(
        curation=curation,
        met_artwork=met_art,
        issue_number=issue_number,
        client=llm_client,
        model=settings.openrouter_drafting_model,
    )

    # Convert MetArtwork dataclass to dict for display & storage
    met_dict = (
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
    )

    # Terminal output
    print("\n" + format_terminal_box("🔍 CURATION REVIEW SUMMARY", html_to_terminal(package.review_summary_html)))
    render_issue_terminal(package.issue_html, met_dict)

    if dry_run:
        print("\n\033[33m[Dry Run] Draft generated successfully. No state saved and no Telegram alerts dispatched.\033[0m\n")
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
        "met_artwork": met_dict,
    }

    draft_id = db.save_draft(draft_payload)
    print(f"\n\033[32m✔ Draft saved to database as Issue #{issue_number} (Draft ID: {draft_id})\033[0m")

    # 7. Send review preview to Bacon's private Telegram chat
    if not no_notify and settings.bot_token and settings.admin_chat_id:
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
            print(f"\033[32m✔ Dispatched draft review to private admin chat ({settings.admin_chat_id})\033[0m")
        except TelegramError as exc:
            print(f"\033[33mWarning: Failed to send review preview to Telegram: {exc}\033[0m", file=sys.stderr)

    print("\nNext step: Run \033[1m./bento publish\033[0m when you are ready to publish this issue to @baconbento.\n")
    db.close()
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    """Preview a pending or specified draft in the terminal."""
    settings = load_settings(require_telegram=False)
    db = Database(settings.db_path)
    issue_id = getattr(args, "issue_id", None)
    draft = db.get_draft(issue_id)

    if not draft:
        target = f" for ID {issue_id}" if issue_id else ""
        print(f"\033[33mNo pending draft found{target}. Run 'bento new' to draft an issue.\033[0m")
        db.close()
        return 1

    issue_number = draft.get("issue_number", "?")
    status = draft.get("status", "unknown")
    created_at = draft.get("created_at", "unknown")

    print(f"\n\033[1mDraft Issue #{issue_number}\033[0m [Status: {status}] (Created: {created_at})")
    render_issue_terminal(draft.get("issue_html", ""), draft.get("met_artwork"))

    if status == "pending":
        print(f"\nReady to publish? Run: \033[1m./bento publish --issue-id {draft['issue_id']}\033[0m\n")

    db.close()
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    """Approve and broadcast a draft to @baconbento."""
    settings = load_settings(require_telegram=True)
    db = Database(settings.db_path)
    issue_id = getattr(args, "issue_id", None)
    skip_confirm = getattr(args, "yes", False)

    draft = db.get_draft(issue_id)
    if not draft:
        target = f" for ID {issue_id}" if issue_id else ""
        print(f"\033[31mError: No pending draft found{target}.\033[0m", file=sys.stderr)
        db.close()
        return 1

    issue_number = draft.get("issue_number", 1)
    issue_html = draft.get("issue_html")
    if not issue_html:
        print("\033[31mError: Draft payload is missing 'issue_html'.\033[0m", file=sys.stderr)
        db.close()
        return 1

    if not skip_confirm:
        confirm = input(f"Publish Issue #{issue_number} to {settings.chat_id}? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Publication cancelled.")
            db.close()
            return 0

    tg = TelegramClient(settings.bot_token, settings.chat_id)
    print(f"Publishing Issue #{issue_number} to {settings.chat_id}...")

    # 1. Send the unified issue text
    try:
        tg.send(issue_html, chat_id=settings.chat_id)
    except TelegramError as exc:
        print(f"\033[31mFailed to publish issue text to Telegram: {exc}\033[0m", file=sys.stderr)
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
            print(f"\033[33mWarning: Issue posted, but failed to post Met artwork: {exc}\033[0m", file=sys.stderr)

    # 3. Mark selected entries as seen/posted in database
    for e in draft.get("selected_entries", []):
        db.mark_seen(e["id"], e.get("feed_url", ""), e.get("title", ""), e.get("link", ""), posted=True)

    # 4. Mark draft as approved
    db.approve_draft(draft["issue_id"])
    print(f"\n\033[32m✔ Issue #{issue_number} successfully approved and broadcast to {settings.chat_id}!\033[0m")

    # Notify admin chat
    if settings.admin_chat_id:
        try:
            tg.send(
                f"✅ <b>Issue #{issue_number} has been published to {settings.chat_id}!</b>",
                chat_id=settings.admin_chat_id,
            )
        except Exception:
            pass

    db.close()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Display hopper metrics and current draft state."""
    settings = load_settings(require_telegram=False)
    db = Database(settings.db_path)
    feeds = load_feeds()
    stats = db.get_hopper_stats()

    content = []
    content.append(f"• Active Feeds in Registry : \033[1m{len(feeds)}\033[0m")

    # Chef's Pantry status
    from pathlib import Path
    obs_path = Path(settings.obsidian_clippings_path).expanduser() if settings.obsidian_clippings_path else None
    obs_count = len([f for f in obs_path.glob("*.md") if not f.name.startswith(("_", "."))]) if (obs_path and obs_path.is_dir()) else 0
    content.append(f"• Chef's Pantry (Obsidian) : \033[1m{obs_count}\033[0m articles in vault")
    content.append(f"• Total Articles Ingested  : {stats['seen_total']}")
    content.append(f"• Articles Published       : {stats['posted_total']}")
    content.append(f"• Met Artworks Displayed   : {stats['met_seen_total']}")
    content.append(f"• Published Issues Total   : \033[1m{stats['published_count']}\033[0m")

    if stats["last_published"]:
        lp = stats["last_published"]
        content.append(f"  └ Last Issue: #{lp.get('issue_number')} on {lp.get('created_at')}")

    content.append("")
    if stats["pending_draft"]:
        pd = stats["pending_draft"]
        content.append(
            f"• \033[33mPending Draft Awaiting Review\033[0m:\n"
            f"  Issue #{pd.get('issue_number')} (Draft ID: {pd.get('issue_id')}, Created: {pd.get('created_at')})\n"
            f"  Run '\033[1m./bento preview\033[0m' to inspect or '\033[1m./bento publish\033[0m' to post."
        )
    else:
        content.append("• Pending Draft : \033[2mNone (ready for new issue via './bento new')\033[0m")

    print("\n" + format_terminal_box("🍱 BACON'S BENTO · HOPPER & STATUS", "\n".join(content)))
    db.close()
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Mark current feed entries as seen without drafting or posting."""
    settings = load_settings(require_telegram=False)
    db = Database(settings.db_path)
    feeds = load_feeds()
    recorded = 0
    print("Ingesting current feed entries for bootstrap...")
    for feed in feeds:
        for entry in fetch_feed(feed):
            if not db.is_seen(entry.id):
                db.mark_seen(entry.id, entry.feed_url, entry.title, entry.link, posted=False)
                recorded += 1
    print(f"\033[32m✔ Bootstrap complete: recorded {recorded} entries without posting.\033[0m")
    db.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bento",
        description="Bacon's Bento: An intentional digital garden & editorial taste engine.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available editorial commands")

    # bento new
    p_new = subparsers.add_parser("new", aliases=["draft"], help="Draft a new Bento issue")
    p_new.add_argument("--dry-run", action="store_true", help="Simulate generation without saving or notifying")
    p_new.add_argument("--no-notify", action="store_true", help="Skip sending draft review to Telegram admin chat")
    p_new.set_defaults(func=cmd_new)

    # bento preview
    p_prev = subparsers.add_parser("preview", aliases=["show"], help="Preview a pending draft in terminal")
    p_prev.add_argument("--issue-id", type=int, default=None, help="Specific draft issue ID (defaults to latest pending)")
    p_prev.set_defaults(func=cmd_preview)

    # bento publish
    p_pub = subparsers.add_parser("publish", aliases=["approve"], help="Approve and broadcast draft to @baconbento")
    p_pub.add_argument("--issue-id", type=int, default=None, help="Specific draft issue ID (defaults to latest pending)")
    p_pub.add_argument("-y", "--yes", action="store_true", help="Skip interactive confirmation")
    p_pub.set_defaults(func=cmd_publish)

    # bento status
    p_stat = subparsers.add_parser("status", help="Inspect hopper metrics and pending draft state")
    p_stat.set_defaults(func=cmd_status)

    # bento bootstrap
    p_boot = subparsers.add_parser("bootstrap", help="Record current feed items as seen without drafting")
    p_boot.set_defaults(func=cmd_bootstrap)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not args.subcommand:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
