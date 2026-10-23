from __future__ import annotations

from pathlib import Path
import pytest

from src.drafts import (
    draft_filename,
    find_draft_note,
    format_draft_note,
    parse_draft_note,
    update_draft_note_frontmatter,
    write_draft_note,
)


def test_draft_filename():
    assert draft_filename(1, "2026-10-22") == "Bacon Bento Vol 1 - 2026-10-22.md"
    assert draft_filename(42, "2026-11-05") == "Bacon Bento Vol 42 - 2026-11-05.md"


def test_write_and_parse_draft_note(tmp_path: Path):
    target = tmp_path / "Bento Issues" / "Bacon Bento Vol 1 - 2026-10-22.md"
    meta = {
        "issue_number": 1,
        "status": "pending",
        "draft_date": "2026-10-22",
        "met_artwork": {
            "title": "Wheat Field",
            "artist": "Van Gogh",
        },
    }
    body = "🍱 <b>Bacon's Bento · Issue #1</b>\n\nIntro copy."

    written_path = write_draft_note(target, meta, body)
    assert written_path.exists()

    content = written_path.read_text(encoding="utf-8")
    parsed_meta, parsed_body = parse_draft_note(content)

    assert parsed_meta["issue_number"] == 1
    assert parsed_meta["status"] == "pending"
    assert parsed_meta["met_artwork"]["title"] == "Wheat Field"
    assert parsed_body == body


def test_update_draft_note_frontmatter(tmp_path: Path):
    target = tmp_path / "Bacon Bento Vol 2 - 2026-10-22.md"
    meta = {"issue_number": 2, "status": "pending"}
    body = "Some body content."
    write_draft_note(target, meta, body)

    updated_meta = update_draft_note_frontmatter(
        target,
        {"status": "published", "published_at": "2026-10-22T20:00:00"},
    )
    assert updated_meta["status"] == "published"
    assert updated_meta["published_at"] == "2026-10-22T20:00:00"

    content = target.read_text(encoding="utf-8")
    parsed_meta, parsed_body = parse_draft_note(content)
    assert parsed_meta["status"] == "published"
    assert parsed_body == body


def test_find_draft_note(tmp_path: Path):
    dir_path = tmp_path / "Bento Issues"
    dir_path.mkdir(parents=True)

    file1 = dir_path / "Bacon Bento Vol 1 - 2026-10-15.md"
    write_draft_note(file1, {"issue_number": 1, "status": "published"}, "Vol 1")

    file2 = dir_path / "Bacon Bento Vol 2 - 2026-10-22.md"
    write_draft_note(file2, {"issue_number": 2, "status": "pending"}, "Vol 2")

    # Find by specific issue number
    assert find_draft_note(dir_path, issue_number=1) == file1
    assert find_draft_note(dir_path, issue_number=2) == file2
    assert find_draft_note(dir_path, issue_number=99) is None

    # Find latest pending
    assert find_draft_note(dir_path, issue_number=None) == file2
