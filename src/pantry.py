"""Chef's Pantry ingestion: Obsidian Clippings vault & Telegram Bot DMs."""
from __future__ import annotations

import calendar
import datetime
import logging
import re
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import requests
import yaml
from bs4 import BeautifulSoup

from .db import entry_id
from .parser import Entry, clean_text

log = logging.getLogger(__name__)

USER_AGENT = "BaconsBento/1.0 (+https://t.me/baconbento)"


def _map_topic_to_course(topic_val) -> str:
    """Map Obsidian frontmatter topic/tags to Bento courses."""
    tokens = []
    if isinstance(topic_val, list):
        tokens = [str(t).lower() for t in topic_val]
    elif isinstance(topic_val, str):
        tokens = [t.strip().lower() for t in topic_val.split(",")]

    all_text = " ".join(tokens)

    # 1. Craft
    if any(k in all_text for k in ("craft", "engineering", "code", "programming", "math", "science", "software", "ai/craft")):
        return "craft"
    # 2. Anchor
    if any(k in all_text for k in ("philosophy", "ethics", "psychology", "mind", "human condition", "interiority", "meaning")):
        return "anchor"
    # 3. Garnish
    if any(k in all_text for k in ("history", "archival", "oddity", "oddities", "curiosity", "art", "antiquity")):
        return "garnish"
    # Default to The Lens (investigation, deep narrative, geopolitics, culture)
    return "lens"


def _parse_frontmatter(content: str) -> Tuple[dict, str]:
    """Extract YAML frontmatter and body from Markdown text."""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    try:
        fm = yaml.safe_load(parts[1]) or {}
        return (fm if isinstance(fm, dict) else {}), parts[2].strip()
    except Exception as exc:
        log.debug("Failed to parse YAML frontmatter: %s", exc)
        return {}, parts[2].strip()


def _date_to_timestamp(val) -> float:
    """Convert string/date/datetime from frontmatter to unix timestamp."""
    if not val:
        return 0.0
    if isinstance(val, (datetime.datetime, datetime.date)):
        if isinstance(val, datetime.date) and not isinstance(val, datetime.datetime):
            val = datetime.datetime.combine(val, datetime.time.min)
        return float(calendar.timegm(val.timetuple()))
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
            try:
                dt = datetime.datetime.strptime(val.strip(), fmt)
                return float(calendar.timegm(dt.timetuple()))
            except ValueError:
                continue
    return 0.0


def ingest_obsidian_clippings(
    vault_dir: Path | str,
    is_seen: Callable[[str], bool],
    max_age_days: int = 30,
) -> List[Entry]:
    """Ingest unread markdown articles from an Obsidian Clippings folder within recency window."""
    path = Path(vault_dir).expanduser()
    if not path.exists() or not path.is_dir():
        log.warning("Obsidian clippings directory not found: %s", path)
        return []

    cutoff = time.time() - (max_age_days * 86400) if max_age_days > 0 else 0.0
    entries: List[Entry] = []
    for file_path in path.glob("*.md"):
        if file_path.name.startswith("_") or file_path.name.startswith("."):
            continue

        try:
            raw_text = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            log.warning("Could not read clipping %s: %s", file_path.name, exc)
            continue

        fm, body = _parse_frontmatter(raw_text)
        link = (fm.get("source") or "").strip()
        if not link or not link.startswith("http"):
            continue

        created_ts = _date_to_timestamp(fm.get("created"))
        published_ts = _date_to_timestamp(fm.get("published"))
        effective_ts = created_ts or published_ts
        if effective_ts == 0.0:
            try:
                effective_ts = file_path.stat().st_mtime
            except OSError:
                pass

        # Filter out articles older than the recency window
        if cutoff > 0 and effective_ts > 0 and effective_ts < cutoff:
            log.debug("Skipping stale Obsidian clipping %s (ts: %s < cutoff: %s)", file_path.name, effective_ts, cutoff)
            continue

        eid = entry_id(None, link)
        if is_seen(eid):
            continue

        title = fm.get("title") or file_path.stem
        description = fm.get("description") or ""
        if not description and body:
            # Strip markdown images and headers
            cleaned_body = re.sub(r"!\[\[.*?\]\]", "", body)
            cleaned_body = re.sub(r"!\[.*?\]\(.*?\)", "", cleaned_body)
            cleaned_body = re.sub(r"^#+\s+.*$", "", cleaned_body, flags=re.MULTILINE)
            description = cleaned_body[:400]

        summary = clean_text(description, 280)
        course = _map_topic_to_course(fm.get("topic") or fm.get("tags"))
        published_ts = _date_to_timestamp(fm.get("published") or fm.get("created"))

        entries.append(
            Entry(
                id=eid,
                feed_url="obsidian://clippings",
                source_tag="Obsidian",
                source_name="Chef's Pantry",
                title=clean_text(str(title), 200),
                link=link,
                summary=summary,
                published=published_ts,
                course=course,
            )
        )

    log.info("Ingested %d unseen Obsidian clippings from %s", len(entries), path)
    return entries


def fetch_page_metadata(url: str) -> Tuple[str, str]:
    """Best-effort page title and description resolution."""
    title = ""
    desc = ""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=4.0,
            allow_redirects=True,
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text[:60000], "html.parser")
            if soup.title and soup.title.string:
                title = clean_text(soup.title.string, 200)

            desc_tag = (
                soup.find("meta", attrs={"name": "description"})
                or soup.find("meta", attrs={"property": "og:description"})
                or soup.find("meta", attrs={"name": "twitter:description"})
            )
            if desc_tag and desc_tag.get("content"):
                desc = clean_text(desc_tag["content"], 300)
    except Exception:
        pass
    return title, desc


def _fetch_page_title(url: str) -> str:
    """Best-effort page title resolution for bare links."""
    return fetch_page_metadata(url)[0]


def save_clipping_note(
    clippings_dir: Path | str,
    title: str,
    url: str,
    summary: str = "",
    course: str = "lens",
    date_ts: float = 0.0,
    commentary: str = "",
) -> Optional[Path]:
    """Save an article clipping note directly into the Obsidian Clippings vault."""
    path = Path(clippings_dir).expanduser()
    if not path.exists() or not path.is_dir():
        return None

    date_str = (
        datetime.datetime.fromtimestamp(date_ts).strftime("%Y-%m-%d %H:%M:%S")
        if date_ts > 0
        else datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    clean_name = re.sub(r'[\\/*?:"<>|]', "", title).strip() or "Clipping"
    target_file = path / f"{clean_name[:60]}.md"

    if target_file.exists():
        try:
            if url in target_file.read_text(encoding="utf-8"):
                return target_file
        except Exception:
            pass
        target_file = path / f"{clean_name[:50]} ({int(time.time())}).md"

    body_text = f"\n{commentary.strip()}\n" if commentary.strip() else ""
    safe_title = title.replace('"', '\\"')
    safe_summary = summary.replace('"', '\\"')
    content = (
        "---\n"
        f'title: "{safe_title}"\n'
        f'source: "{url}"\n'
        "topic:\n"
        f'  - "{course}"\n'
        f'description: "{safe_summary}"\n'
        f'created: "{date_str}"\n'
        "tags:\n"
        "  - clippings\n"
        "  - telegram\n"
        "---\n"
        f"{body_text}"
    )
    try:
        target_file.write_text(content, encoding="utf-8")
        log.info("Saved clipping note to Obsidian: %s", target_file.name)
        return target_file
    except Exception as exc:
        log.warning("Could not write clipping note %s: %s", target_file, exc)
        return None


def ingest_telegram_pantry(
    bot_token: str,
    admin_chat_id: str,
    is_seen: Callable[[str], bool],
    offset: Optional[int] = None,
    acknowledge: bool = False,
    max_age_days: int = 30,
    clippings_dir: Optional[Path | str] = None,
) -> Tuple[List[Entry], Optional[int]]:
    """Poll private Telegram Bot messages forwarded by the admin curator within recency window."""
    if not bot_token:
        return [], offset

    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params = {"timeout": 3}
    if offset is not None:
        params["offset"] = offset

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
    except Exception as exc:
        log.warning("Failed to fetch Telegram pantry updates: %s", exc)
        return [], offset

    if not data.get("ok"):
        log.warning("Telegram getUpdates returned error: %s", data.get("description"))
        return [], offset

    updates = data.get("result", [])
    if not updates:
        return [], offset

    entries: List[Entry] = []
    seen_links = set()
    cutoff = time.time() - (max_age_days * 86400) if max_age_days > 0 else 0.0

    for u in updates:
        msg = u.get("message") or u.get("channel_post")
        if not msg:
            continue

        # Security check: only allow admin curator
        from_id = msg.get("from", {}).get("id")
        if admin_chat_id and str(from_id) != str(admin_chat_id):
            log.debug("Skipping message from unauthorized sender %s", from_id)
            continue

        date_ts = float(msg.get("date", 0))
        if cutoff > 0 and date_ts > 0 and date_ts < cutoff:
            log.debug("Skipping stale Telegram drop (ts: %s < cutoff: %s)", date_ts, cutoff)
            continue

        text = msg.get("text") or msg.get("caption") or ""
        urls = []

        # 1. Parse entity links
        entities = msg.get("entities") or msg.get("caption_entities") or []
        for ent in entities:
            etype = ent.get("type")
            if etype == "text_link" and ent.get("url"):
                urls.append(ent.get("url"))

        # 2. Extract any URLs present in text via regex
        for found_url in re.findall(r"https?://[^\s<>\"']+", text):
            if found_url not in urls:
                urls.append(found_url)

        if not urls:
            continue

        # Detect course from hashtag/keyword (default to lens)
        course = "lens"
        for c in ("anchor", "lens", "craft", "garnish"):
            if f"#{c}" in text.lower() or f"course:{c}" in text.lower():
                course = c
                break

        # Extract title/commentary from text excluding URLs and tags
        clean_prompt_text = re.sub(r"https?://[^\s<>\"']+", "", text)
        clean_prompt_text = re.sub(r"#(anchor|lens|craft|garnish)\b", "", clean_prompt_text, flags=re.IGNORECASE)
        title_text = clean_text(clean_prompt_text.strip(), 200)

        date_ts = float(msg.get("date", 0))

        for target_url in urls:
            target_url = target_url.strip()
            if not target_url.startswith("http") or target_url in seen_links:
                continue

            eid = entry_id(None, target_url)
            if is_seen(eid):
                continue

            seen_links.add(target_url)

            # If user provided a title in text, use it; otherwise fetch HTML <title> & description
            final_title = title_text
            meta_desc = ""
            if not final_title or len(final_title) < 5:
                resolved_title, meta_desc = fetch_page_metadata(target_url)
                final_title = resolved_title or target_url.split("//")[-1].split("/")[0]

            summary = clean_text(title_text or meta_desc or f"Shared via Telegram: {target_url}", 280)

            # Automatically mirror to Obsidian Clippings folder if configured
            if clippings_dir:
                save_clipping_note(
                    clippings_dir=clippings_dir,
                    title=final_title,
                    url=target_url,
                    summary=summary,
                    course=course,
                    date_ts=date_ts,
                    commentary=title_text if title_text != final_title else "",
                )

            entries.append(
                Entry(
                    id=eid,
                    feed_url="telegram://pantry",
                    source_tag="Telegram",
                    source_name="Chef's Pantry",
                    title=final_title,
                    link=target_url,
                    summary=summary,
                    published=date_ts,
                    course=course,
                )
            )

    next_offset = offset
    if updates:
        max_id = max(u["update_id"] for u in updates)
        next_offset = max_id + 1
        if acknowledge:
            try:
                requests.get(url, params={"offset": next_offset, "timeout": 0}, timeout=5)
                log.info("Acknowledged Telegram pantry updates up to offset %d", next_offset)
            except Exception as exc:
                log.warning("Failed to acknowledge Telegram offset: %s", exc)

    return entries, next_offset


def collect_candidates(
    feeds: List,
    settings,
    db,
    dry_run: bool = False,
) -> Tuple[List[Entry], dict]:
    """Collect unseen candidates across RSS feeds, Obsidian clippings, and Telegram drops."""
    from .parser import fetch_feed

    candidates: List[Entry] = []
    seen_in_batch = set()
    rss_count = 0

    # 1. Ingest RSS Feeds
    for feed in feeds:
        for entry in fetch_feed(feed):
            if entry.id in seen_in_batch or db.is_seen(entry.id):
                continue
            seen_in_batch.add(entry.id)
            candidates.append(entry)
            rss_count += 1

    # 2. Ingest Chef's Pantry: Obsidian Clippings
    obsidian_entries = []
    max_age_days = int(getattr(settings, "pantry_max_age_days", 30))
    if getattr(settings, "obsidian_clippings_path", ""):
        obsidian_entries = ingest_obsidian_clippings(
            settings.obsidian_clippings_path,
            is_seen=lambda eid: eid in seen_in_batch or db.is_seen(eid),
            max_age_days=max_age_days,
        )
        for e in obsidian_entries:
            seen_in_batch.add(e.id)
            candidates.append(e)

    # 3. Ingest Chef's Pantry: Telegram Bot Forwards
    telegram_entries = []
    bot_token = getattr(settings, "bot_token", "")
    admin_chat_id = getattr(settings, "admin_chat_id", "")
    if bot_token and admin_chat_id:
        last_offset_str = db.get_kv("telegram_pantry_offset")
        last_offset = int(last_offset_str) if last_offset_str else None
        telegram_entries, next_offset = ingest_telegram_pantry(
            bot_token=bot_token,
            admin_chat_id=admin_chat_id,
            is_seen=lambda eid: eid in seen_in_batch or db.is_seen(eid),
            offset=last_offset,
            acknowledge=(not dry_run),
            max_age_days=max_age_days,
            clippings_dir=getattr(settings, "obsidian_clippings_path", None) if not dry_run else None,
        )
        for e in telegram_entries:
            seen_in_batch.add(e.id)
            candidates.append(e)
        if not dry_run and next_offset is not None:
            db.set_kv("telegram_pantry_offset", str(next_offset))

    breakdown = {
        "rss": rss_count,
        "obsidian": len(obsidian_entries),
        "telegram": len(telegram_entries),
        "total": len(candidates),
    }
    return candidates, breakdown

