"""Bacon's Bento CLI: intentional, on-demand editorial commands."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
import sys
import time
from typing import Optional, Sequence
from urllib.parse import urlsplit

from .config import load_feeds, load_registry, load_settings
from .curator import CurationDecision, CurationResult, curate_candidates
from .db import Database, entry_id
from .drafter import draft_issue_package
from .drafts import (
    draft_filename,
    find_draft_note,
    parse_draft_note,
    update_draft_note_frontmatter,
    write_draft_note,
)
from .formatter import (
    TG_CAPTION_LIMIT,
    TG_LIMIT,
    format_met_caption,
    format_terminal_box,
    html_to_terminal,
    markdown_to_telegram_html,
    validate_telegram_html,
)
from .llm import OpenRouterClient
from .met import MetArtwork, fetch_met_artwork
from .pantry import collect_candidates, fetch_page_metadata, save_clipping_note
from .parser import Entry, fetch_feed
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
    curation = curate_candidates(
        candidates,
        llm_client,
        model=settings.openrouter_decision_model,
        fallback_model=settings.openrouter_drafting_model,
    )

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

    # Determine Obsidian draft file path & write note
    draft_date = datetime.now().strftime("%Y-%m-%d")
    draft_file_path: Optional[str] = None
    if getattr(settings, "bento_issues_path", ""):
        issues_dir = Path(settings.bento_issues_path).expanduser()
        filename = draft_filename(issue_number, draft_date)
        target_path = issues_dir / filename
        meta = {
            "issue_number": issue_number,
            "status": "pending",
            "draft_date": draft_date,
            "met_artwork": met_dict,
            "selected_entries": [
                {
                    "id": e.id,
                    "title": e.title,
                    "link": e.link,
                    "course": e.course,
                    "source": e.source_name,
                }
                for e in curation.selected_entries
            ],
        }
        try:
            write_draft_note(target_path, meta, package.issue_html)
            draft_file_path = str(target_path)
            print(f"\033[32m✔ Saved draft note to Obsidian: {target_path}\033[0m")
        except Exception as exc:
            log.warning("Could not write Obsidian draft note: %s", exc)
            print(f"\033[33mWarning: Could not write Obsidian draft note: {exc}\033[0m", file=sys.stderr)

    if dry_run:
        print("\n\033[33m[Dry Run] Draft generated successfully. No state saved and no Telegram alerts dispatched.\033[0m\n")
        db.close()
        return 0

    # 6. Save draft in database
    draft_payload = {
        "issue_number": issue_number,
        "issue_html": package.issue_html,
        "file_path": draft_file_path,
        "draft_date": draft_date,
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

    if draft_file_path:
        try:
            update_draft_note_frontmatter(Path(draft_file_path), {"draft_id": draft_id})
        except Exception:
            pass

    # 7. Send review preview to Bacon's private Telegram chat
    if not no_notify and settings.bot_token and settings.admin_chat_id:
        tg = TelegramClient(settings.bot_token, settings.admin_chat_id)
        try:
            tg.send(package.review_summary_html, chat_id=settings.admin_chat_id)
            if package.met_artwork:
                caption = format_met_caption(package.met_artwork)
                tg.send_photo(package.met_artwork.image_url, caption=caption, chat_id=settings.admin_chat_id)
            print(f"\033[32m✔ Dispatched draft review to private admin chat ({settings.admin_chat_id})\033[0m")
        except TelegramError as exc:
            print(f"\033[33mWarning: Failed to send review preview to Telegram: {exc}\033[0m", file=sys.stderr)

    print("\nNext step: Run \033[1m./bento publish\033[0m when you are ready to publish this issue to @baconbento.\n")
    db.close()
    return 0


@dataclass
class ResolvedDraft:
    draft: Optional[dict]
    draft_file: Optional[Path]
    issue_number: Any
    status: str
    created_at: str
    issue_html: str
    met_data: Optional[dict]
    selected_entries: list


def resolve_draft(db: Database, settings: Any, issue_id: Optional[int] = None) -> Optional[ResolvedDraft]:
    """Find and sync draft from SQLite and Obsidian vault."""
    draft = db.get_draft(issue_id)
    issues_dir = Path(settings.bento_issues_path).expanduser() if getattr(settings, "bento_issues_path", "") else None
    draft_file: Optional[Path] = None

    if draft:
        file_path_str = draft.get("file_path")
        if file_path_str and Path(file_path_str).exists():
            draft_file = Path(file_path_str)
        elif issues_dir and issues_dir.exists():
            draft_file = find_draft_note(issues_dir, draft.get("issue_number"))
    elif issues_dir and issues_dir.exists():
        draft_file = find_draft_note(issues_dir, issue_id)

    if not draft and not draft_file:
        return None

    issue_number = (draft.get("issue_number") if draft else None) or 1
    status = (draft.get("status") if draft else None) or "pending"
    created_at = (draft.get("created_at") if draft else None) or "recent"
    issue_html = draft.get("issue_html", "") if draft else ""
    met_data = draft.get("met_artwork") if draft else None
    selected_entries = draft.get("selected_entries", []) if draft else []

    if draft_file and draft_file.exists():
        try:
            meta, body = parse_draft_note(draft_file.read_text(encoding="utf-8"))
            if meta:
                issue_number = meta.get("issue_number", issue_number)
                status = meta.get("status", status)
                if meta.get("met_artwork"):
                    met_data = meta.get("met_artwork")
                if not selected_entries and meta.get("selected_entries"):
                    selected_entries = meta.get("selected_entries")
            if body:
                issue_html = markdown_to_telegram_html(body)
        except Exception as exc:
            log.warning("Could not read draft file %s: %s", draft_file, exc)

    return ResolvedDraft(
        draft=draft,
        draft_file=draft_file,
        issue_number=issue_number,
        status=status,
        created_at=created_at,
        issue_html=issue_html,
        met_data=met_data,
        selected_entries=selected_entries,
    )


def cmd_preview(args: argparse.Namespace) -> int:
    """Preview a pending or specified draft in the terminal."""
    settings = load_settings(require_telegram=False)
    db = Database(settings.db_path)
    issue_id = getattr(args, "issue_id", None)
    d = resolve_draft(db, settings, issue_id)

    if not d:
        target = f" for ID {issue_id}" if issue_id else ""
        print(f"\033[33mNo pending draft found{target}. Run 'bento new' to draft an issue.\033[0m")
        db.close()
        return 1

    file_tag = f" [Obsidian: {d.draft_file.name}]" if d.draft_file else ""
    print(f"\n\033[1mDraft Issue #{d.issue_number}\033[0m [Status: {d.status}] (Created: {d.created_at}){file_tag}")
    render_issue_terminal(d.issue_html, d.met_data)

    if d.status == "pending":
        issue_ref = f" --issue-id {d.draft['issue_id']}" if d.draft and "issue_id" in d.draft else ""
        print(f"\nReady to publish? Run: \033[1m./bento publish{issue_ref}\033[0m\n")

    db.close()
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    """Validate Markdown/HTML tag nesting and character limits before broadcasting."""
    settings = load_settings(require_telegram=False)
    db = Database(settings.db_path)
    issue_id = getattr(args, "issue_id", None)
    d = resolve_draft(db, settings, issue_id)

    if not d:
        target = f" for ID {issue_id}" if issue_id else ""
        print(f"\033[31mError: No draft found{target} to lint.\033[0m", file=sys.stderr)
        db.close()
        return 1

    if d.draft_file:
        print(f"Linting draft from Obsidian: \033[1m{d.draft_file.name}\033[0m")

    caption = format_met_caption(d.met_data) if d.met_data else ""
    errors = validate_telegram_html(d.issue_html, TG_LIMIT)
    if caption:
        caption_errors = validate_telegram_html(caption, TG_CAPTION_LIMIT)
        errors.extend(f"[Artwork Caption] {err}" for err in caption_errors)

    if errors:
        print(f"\n\033[31m❌ Issue #{d.issue_number} failed Telegram lint guards ({len(errors)} error(s)):\033[0m")
        for err in errors:
            print(f"  • {err}")
        db.close()
        return 1

    print(f"\033[32m✔ Issue #{d.issue_number} passed Telegram format & character guards.\033[0m")
    print(f"  • Issue text: {len(d.issue_html)}/{TG_LIMIT} chars")
    if caption:
        print(f"  • Met caption: {len(caption)}/{TG_CAPTION_LIMIT} chars")
    db.close()
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    """Approve and broadcast a draft to @baconbento."""
    settings = load_settings(require_telegram=True)
    db = Database(settings.db_path)
    issue_id = getattr(args, "issue_id", None)
    skip_confirm = getattr(args, "yes", False)

    d = resolve_draft(db, settings, issue_id)

    if not d:
        target = f" for ID {issue_id}" if issue_id else ""
        print(f"\033[31mError: No pending draft found{target}.\033[0m", file=sys.stderr)
        db.close()
        return 1

    if d.draft_file:
        print(f"Loaded edited draft from Obsidian: \033[1m{d.draft_file.name}\033[0m")

    if not d.issue_html:
        print("\033[31mError: Draft payload is missing 'issue_html'.\033[0m", file=sys.stderr)
        db.close()
        return 1

    # Pre-flight format & character guard
    caption = format_met_caption(d.met_data) if d.met_data else ""
    errors = validate_telegram_html(d.issue_html, TG_LIMIT)
    if caption:
        caption_errors = validate_telegram_html(caption, TG_CAPTION_LIMIT)
        errors.extend(f"[Artwork Caption] {err}" for err in caption_errors)

    if errors:
        print(f"\033[31mError: Cannot publish Issue #{d.issue_number} — failed Telegram guards:\033[0m", file=sys.stderr)
        for err in errors:
            print(f"  • {err}", file=sys.stderr)
        db.close()
        return 1

    if not skip_confirm:
        confirm = input(f"Publish Issue #{d.issue_number} to {settings.chat_id}? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Publication cancelled.")
            db.close()
            return 0

    tg = TelegramClient(settings.bot_token, settings.chat_id)
    print(f"Publishing Issue #{d.issue_number} to {settings.chat_id}...")

    # 1. Send the unified issue text
    try:
        tg.send(d.issue_html, chat_id=settings.chat_id)
    except TelegramError as exc:
        print(f"\033[31mFailed to publish issue text to Telegram: {exc}\033[0m", file=sys.stderr)
        db.close()
        return 1

    # 2. Send the Met artwork photo if present
    if d.met_data and d.met_data.get("image_url"):
        try:
            tg.send_photo(d.met_data["image_url"], caption=caption, chat_id=settings.chat_id)
            if d.met_data.get("object_id"):
                db.mark_met_seen(d.met_data["object_id"], d.met_data.get("title", ""))
        except TelegramError as exc:
            print(f"\033[33mWarning: Issue posted, but failed to post Met artwork: {exc}\033[0m", file=sys.stderr)

    # 3. Mark selected entries as seen/posted in database
    for e in d.selected_entries:
        db.mark_seen(e["id"], e.get("feed_url", ""), e.get("title", ""), e.get("link", ""), posted=True)

    # 4. Mark draft as approved
    if d.draft and "issue_id" in d.draft:
        db.approve_draft(d.draft["issue_id"])

    # 5. Update Obsidian note frontmatter to status: published
    if d.draft_file and d.draft_file.exists():
        try:
            update_draft_note_frontmatter(
                d.draft_file,
                {
                    "status": "published",
                    "published_at": datetime.now().isoformat(timespec="seconds"),
                },
            )
            print(f"\033[32m✔ Updated Obsidian note status to 'published' ({d.draft_file.name})\033[0m")
        except Exception as exc:
            log.warning("Could not update Obsidian note status: %s", exc)

    print(f"\n\033[32m✔ Issue #{d.issue_number} successfully approved and broadcast to {settings.chat_id}!\033[0m")

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


def cmd_update(args: argparse.Namespace) -> int:
    """Update a pending draft with a featured article URL and re-synthesize."""
    settings = load_settings(require_telegram=False)
    db = Database(settings.db_path)
    target_url = getattr(args, "url", None) or getattr(args, "link", None)
    course_arg = getattr(args, "course", None)
    issue_id = getattr(args, "issue_id", None)
    no_notify = getattr(args, "no_notify", False)

    draft = db.get_draft(issue_id)
    issues_dir = Path(settings.bento_issues_path).expanduser() if getattr(settings, "bento_issues_path", "") else None
    draft_file: Optional[Path] = None

    if draft:
        file_path_str = draft.get("file_path")
        if file_path_str and Path(file_path_str).exists():
            draft_file = Path(file_path_str)
        elif issues_dir and issues_dir.exists():
            draft_file = find_draft_note(issues_dir, draft.get("issue_number"))
    elif issues_dir and issues_dir.exists():
        draft_file = find_draft_note(issues_dir, issue_id)

    if not draft or draft.get("status") != "pending":
        target = f" for ID {issue_id}" if issue_id else ""
        print(f"\033[31mError: No pending draft found{target} to update. Run './bento new' first.\033[0m", file=sys.stderr)
        db.close()
        return 1

    if not target_url:
        print("\033[31mError: Please provide an article URL to feature (e.g. ./bento update https://example.com/article).\033[0m", file=sys.stderr)
        db.close()
        return 1

    target_url = target_url.strip()
    if not target_url.startswith("http"):
        print(f"\033[31mError: Invalid URL '{target_url}'. Must begin with http:// or https://\033[0m", file=sys.stderr)
        db.close()
        return 1

    # 1. Fetch metadata for the article
    print(f"Fetching metadata for \033[1m{target_url}\033[0m...")
    title, summary = fetch_page_metadata(target_url)
    domain = urlsplit(target_url).netloc
    if domain.startswith("www."):
        domain = domain[4:]
    final_title = title or domain
    final_summary = summary or f"Featured read from {domain}."

    existing_entries = draft.get("selected_entries", [])
    if course_arg:
        course = course_arg.lower()
        if course not in ("anchor", "lens", "craft", "garnish"):
            print(f"\033[31mError: Invalid course '{course}'. Must be one of: anchor, lens, craft, garnish\033[0m", file=sys.stderr)
            db.close()
            return 1
    else:
        occupied = {e.get("course") for e in existing_entries}
        course = next((c for c in ("lens", "anchor", "craft", "garnish") if c not in occupied), "lens")

    eid = entry_id(None, target_url)
    new_entry = {
        "id": eid,
        "feed_url": "manual://update",
        "title": final_title,
        "link": target_url,
        "course": course,
        "source": domain,
        "summary": final_summary,
    }

    # 2. Automatically save as clipping note if Obsidian vault configured
    if getattr(settings, "obsidian_clippings_path", ""):
        save_clipping_note(
            clippings_dir=settings.obsidian_clippings_path,
            title=final_title,
            url=target_url,
            summary=final_summary,
            course=course,
            commentary="Featured via 'bento update'",
        )

    # 3. Update draft's selected_entries: replace entry for that course
    updated_entries = [e for e in existing_entries if e.get("course") != course]
    updated_entries.append(new_entry)

    course_order = {"anchor": 0, "lens": 1, "craft": 2, "garnish": 3}
    updated_entries.sort(key=lambda e: course_order.get(e.get("course", "lens"), 99))

    issue_number = draft.get("issue_number", 1)
    met_data = draft.get("met_artwork")
    met_artwork = None
    if met_data:
        met_artwork = MetArtwork(
            object_id=met_data.get("object_id", 0),
            title=met_data.get("title", ""),
            artist=met_data.get("artist", ""),
            date=met_data.get("date", ""),
            medium=met_data.get("medium", ""),
            department=met_data.get("department", ""),
            object_url=met_data.get("object_url", ""),
            image_url=met_data.get("image_url", ""),
        )

    # 4. Re-synthesize issue using Drafter Model
    print(f"Re-synthesizing Issue #{issue_number} with Drafter Model ({settings.openrouter_drafting_model})...")
    llm_client = OpenRouterClient(api_key=settings.openrouter_api_key)

    decisions = {}
    selected_objs = []
    for e in updated_entries:
        entry_obj = Entry(
            id=e["id"],
            feed_url=e.get("feed_url", ""),
            source_tag="Curator",
            source_name=e.get("source", domain),
            title=e["title"],
            link=e["link"],
            summary=e.get("summary", ""),
            published=time.time(),
            course=e["course"],
        )
        decisions[e["course"]] = CurationDecision(
            course=e["course"],
            entry=entry_obj,
            rationale=f"Curator featured article for {e['course'].title()}",
        )
        selected_objs.append(entry_obj)

    curation = CurationResult(decisions=decisions, selected_entries=selected_objs)

    package = draft_issue_package(
        curation=curation,
        met_artwork=met_artwork,
        issue_number=issue_number,
        client=llm_client,
        model=settings.openrouter_drafting_model,
    )

    # 5. Update SQLite Database
    draft["issue_html"] = package.issue_html
    draft["selected_entries"] = updated_entries
    db.update_draft(draft["issue_id"], draft)

    # 6. Update Obsidian draft note
    if draft_file and draft_file.exists():
        try:
            write_draft_note(
                draft_file,
                {
                    "issue_number": issue_number,
                    "status": "pending",
                    "draft_date": draft.get("draft_date", datetime.now().strftime("%Y-%m-%d")),
                    "met_artwork": met_data,
                    "selected_entries": updated_entries,
                    "draft_id": draft["issue_id"],
                },
                package.issue_html,
            )
            print(f"\033[32m✔ Synchronized updated draft to Obsidian: {draft_file.name}\033[0m")
        except Exception as exc:
            log.warning("Could not update Obsidian note: %s", exc)

    # 7. Dispatch updated review to Telegram admin chat
    if not no_notify and settings.bot_token and settings.admin_chat_id:
        tg = TelegramClient(settings.bot_token, settings.admin_chat_id)
        try:
            tg.send(package.review_summary_html, chat_id=settings.admin_chat_id)
            if package.met_artwork:
                caption = format_met_caption(package.met_artwork)
                tg.send_photo(package.met_artwork.image_url, caption=caption, chat_id=settings.admin_chat_id)
            print(f"\033[32m✔ Dispatched updated review to admin chat ({settings.admin_chat_id})\033[0m")
        except TelegramError as exc:
            print(f"\033[33mWarning: Failed to send Telegram review: {exc}\033[0m", file=sys.stderr)

    # 8. Terminal output
    print("\n" + format_terminal_box("🔍 UPDATED DRAFT REVIEW SUMMARY", html_to_terminal(package.review_summary_html)))
    render_issue_terminal(package.issue_html, met_data)
    print(f"\n\033[32m✔ Issue #{issue_number} updated with '{final_title}' ({course.title()})!\033[0m")
    print(f"Ready to publish? Run: \033[1m./bento publish\033[0m\n")

    db.close()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Display hopper metrics, per-course candidate depth, and health warnings."""
    settings = load_settings(require_telegram=False)
    db = Database(settings.db_path)
    feeds = load_feeds()
    stats = db.get_hopper_stats()

    # Collect unseen candidates across feeds and pantry without mutating state
    candidates, breakdown = collect_candidates(feeds, settings, db, dry_run=True)

    content = []
    content.append(f"• Active Feeds in Registry : \033[1m{len(feeds)}\033[0m")
    content.append(
        f"• Chef's Pantry            : {breakdown['obsidian']} active clipping(s) · {breakdown['telegram']} Telegram drop(s)"
    )
    content.append(
        f"• Total Unseen in Hopper   : \033[1m{breakdown['total']}\033[0m candidates "
        f"({breakdown['rss']} RSS, {breakdown['obsidian']} Obsidian, {breakdown['telegram']} Telegram)"
    )
    content.append("")

    # Course hopper depth & health warnings
    by_course: dict[str, list] = {"anchor": [], "lens": [], "craft": [], "garnish": []}
    for e in candidates:
        c = e.course.lower()
        if c in by_course:
            by_course[c].append(e)
        else:
            by_course.setdefault(c, []).append(e)

    content.append("• Course Hopper Depth:")
    course_keys = list(by_course.keys())
    for i, c in enumerate(course_keys):
        prefix = "└─" if i == len(course_keys) - 1 else "├─"
        n = len(by_course[c])
        if n == 0:
            health = "\033[31m❌ STARVING\033[0m (0 candidates)"
        elif n == 1:
            health = "\033[33m⚠️ LOW\033[0m (1 candidate)"
        else:
            health = f"\033[32m✔ Healthy\033[0m ({n} candidates)"
        content.append(f"  {prefix} {c.title():<8} : {n} candidates  [{health}]")

    # Starving feeds (registered feeds that yielded 0 unseen items)
    candidate_feed_urls = {e.feed_url for e in candidates if e.feed_url}
    starving_feeds = [f for f in feeds if f.url not in candidate_feed_urls]
    if starving_feeds:
        content.append("")
        content.append(f"• \033[33mStarving Feeds ({len(starving_feeds)} with 0 unseen items)\033[0m:")
        for sf in starving_feeds:
            content.append(f"  • {sf.name} ({sf.course.title()})")

    content.append("")
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

    # bento lint
    p_lint = subparsers.add_parser("lint", aliases=["check"], help="Validate Telegram tag nesting and character limits")
    p_lint.add_argument("--issue-id", type=int, default=None, help="Specific draft issue ID (defaults to latest pending)")
    p_lint.set_defaults(func=cmd_lint)

    # bento publish
    p_pub = subparsers.add_parser("publish", aliases=["approve"], help="Approve and broadcast draft to @baconbento")
    p_pub.add_argument("--issue-id", type=int, default=None, help="Specific draft issue ID (defaults to latest pending)")
    p_pub.add_argument("-y", "--yes", action="store_true", help="Skip interactive confirmation")
    p_pub.set_defaults(func=cmd_publish)

    # bento update
    p_upd = subparsers.add_parser("update", help="Update pending draft with a featured article URL and re-synthesize")
    p_upd.add_argument("url", nargs="?", default=None, help="URL of article to feature")
    p_upd.add_argument("--link", "--url", dest="link", default=None, help="Alternative flag for article URL")
    p_upd.add_argument("--course", choices=["anchor", "lens", "craft", "garnish"], default=None, help="Target course for article (default: lens)")
    p_upd.add_argument("--issue-id", type=int, default=None, help="Specific draft issue ID (defaults to latest pending)")
    p_upd.add_argument("--no-notify", action="store_true", help="Skip sending updated review to Telegram admin chat")
    p_upd.set_defaults(func=cmd_update)

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
