"""Unit tests for Chef's Pantry ingestion (Obsidian & Telegram)."""
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.pantry import (
    _map_topic_to_course,
    _parse_frontmatter,
    ingest_obsidian_clippings,
    ingest_telegram_pantry,
)


def test_map_topic_to_course():
    assert _map_topic_to_course(["ai/craft"]) == "craft"
    assert _map_topic_to_course(["engineering", "code"]) == "craft"
    assert _map_topic_to_course(["philosophy", "ethics"]) == "anchor"
    assert _map_topic_to_course(["human condition"]) == "anchor"
    assert _map_topic_to_course(["history", "archival"]) == "garnish"
    assert _map_topic_to_course(["geopolitics", "investigation"]) == "lens"
    assert _map_topic_to_course([]) == "lens"
    assert _map_topic_to_course(None) == "lens"


def test_parse_frontmatter():
    doc = """---
title: "Sample Article"
source: "https://example.com/essay"
topic:
  - "ai/craft"
---
# Heading
This is the body content.
"""
    fm, body = _parse_frontmatter(doc)
    assert fm["title"] == "Sample Article"
    assert fm["source"] == "https://example.com/essay"
    assert fm["topic"] == ["ai/craft"]
    assert "# Heading" in body


def test_ingest_obsidian_clippings(tmp_path: Path):
    clippings_dir = tmp_path / "Clippings"
    clippings_dir.mkdir()

    # 1. Valid clipping
    (clippings_dir / "article1.md").write_text(
        """---
title: "Craft of Toolmaking"
source: "https://tools.example.com/craft"
topic:
  - "craft"
description: "A reflection on toolmaking."
published: 2026-10-15
---
Body text.
""",
        encoding="utf-8",
    )

    # 2. Clipping with body fallback for summary
    (clippings_dir / "article2.md").write_text(
        """---
title: "The Silent Anchor"
source: "https://philosophy.example.com/silence"
topic:
  - "philosophy"
---
# Introduction
![[image.png]]
Philosophy begins in quiet contemplation of being.
""",
        encoding="utf-8",
    )

    # 3. MOC note (should be skipped)
    (clippings_dir / "_Clippings MOC.md").write_text(
        """---
title: "MOC"
source: "https://example.com/moc"
---
""",
        encoding="utf-8",
    )

    # 4. Note without source link (should be skipped)
    (clippings_dir / "note_without_link.md").write_text(
        """---
title: "Local Note"
---
Just thoughts.
""",
        encoding="utf-8",
    )

    # 5. Stale clipping (older than 30 days, should be skipped)
    (clippings_dir / "old_article.md").write_text(
        """---
title: "Ancient History of 2025"
source: "https://ancient.example.com/essay"
created: 2025-01-01
---
Stale essay.
""",
        encoding="utf-8",
    )

    seen = set()
    entries = ingest_obsidian_clippings(clippings_dir, is_seen=lambda eid: eid in seen, max_age_days=30)
    assert len(entries) == 2
    assert not any(e.title == "Ancient History of 2025" for e in entries)

    # Check course mapping and metadata
    entry1 = next(e for e in entries if e.title == "Craft of Toolmaking")
    assert entry1.link == "https://tools.example.com/craft"
    assert entry1.course == "craft"
    assert entry1.source_name == "Chef's Pantry"
    assert entry1.source_tag == "Obsidian"
    assert entry1.summary == "A reflection on toolmaking."

    entry2 = next(e for e in entries if e.title == "The Silent Anchor")
    assert entry2.course == "anchor"
    assert "Philosophy begins in quiet contemplation" in entry2.summary
    assert "image.png" not in entry2.summary  # stripped


@patch("src.pantry.requests.get")
def test_ingest_telegram_pantry(mock_get):
    import time
    now_ts = int(time.time())

    sample_response = {
        "ok": True,
        "result": [
            {
                "update_id": 1001,
                "message": {
                    "message_id": 42,
                    "from": {"id": 185121575, "username": "Curator"},
                    "date": now_ts - 3600,
                    "text": "On AI writing\n\nhttps://example.com/ai-writing",
                    "entities": [
                        {"type": "url", "offset": 15, "length": 29}
                    ],
                },
            },
            {
                # Unauthorized sender message
                "update_id": 1002,
                "message": {
                    "message_id": 43,
                    "from": {"id": 999999999, "username": "Stranger"},
                    "date": now_ts - 1000,
                    "text": "Check this: https://spam.com/link",
                },
            },
            {
                # Message without link
                "update_id": 1003,
                "message": {
                    "message_id": 44,
                    "from": {"id": 185121575, "username": "Curator"},
                    "date": now_ts - 500,
                    "text": "Just a text note without any links",
                },
            },
            {
                # Stale message (> 30 days old)
                "update_id": 1004,
                "message": {
                    "message_id": 45,
                    "from": {"id": 185121575, "username": "Curator"},
                    "date": now_ts - (45 * 86400),
                    "text": "Old find: https://example.com/old-find",
                },
            },
        ],
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = sample_response
    mock_get.return_value = mock_resp

    seen = set()
    entries, next_offset = ingest_telegram_pantry(
        bot_token="test_token",
        admin_chat_id="185121575",
        is_seen=lambda eid: eid in seen,
        acknowledge=True,
    )

    assert len(entries) == 1
    e = entries[0]
    assert e.title == "On AI writing"
    assert e.link == "https://example.com/ai-writing"
    assert e.source_name == "Chef's Pantry"
    assert e.source_tag == "Telegram"
    assert e.course == "lens"
    assert next_offset == 1005


def test_chefs_pantry_collision_protection():
    """Verify that Bento's source collision rule ensures at most 1 Chef's Pantry item is selected."""
    import json
    from src.curator import curate_candidates
    from src.parser import Entry

    pantry_craft = Entry(
        id="p1", feed_url="", source_tag="Obsidian", title="Toolmaking",
        link="https://pantry/1", summary="Sum", published=100.0,
        source_name="Chef's Pantry", course="craft",
    )
    pantry_lens = Entry(
        id="p2", feed_url="", source_tag="Telegram", title="AI Writing",
        link="https://pantry/2", summary="Sum", published=100.0,
        source_name="Chef's Pantry", course="lens",
    )

    mock_client = MagicMock()
    # LLM chooses both pantry items for two different courses
    mock_client.complete.return_value = json.dumps({
        "selections": {
            "craft": {"selected_id": "p1", "rationale": "Great craft essay", "rejected_notes": []},
            "lens": {"selected_id": "p2", "rationale": "Great lens essay", "rejected_notes": []},
        }
    })

    result = curate_candidates([pantry_craft, pantry_lens], mock_client)
    # Only 1 Chef's Pantry item should be allowed; the second should be dropped due to source collision
    selected_pantry = [e for e in result.selected_entries if e.source_name == "Chef's Pantry"]
    assert len(selected_pantry) == 1

