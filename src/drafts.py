"""Draft file storage and Obsidian synchronization for Bacon's Bento."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

log = logging.getLogger(__name__)


def draft_filename(issue_number: int, draft_date: str) -> str:
    """Standardized Obsidian-sync safe filename."""
    return f"Bacon Bento Vol {issue_number} - {draft_date}.md"


def parse_draft_note(content: str) -> Tuple[Dict[str, Any], str]:
    """Extract YAML frontmatter and body text from a draft markdown note."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body = parts[2].strip()
            try:
                data = yaml.safe_load(fm_text) or {}
                if isinstance(data, dict):
                    return data, body
            except yaml.YAMLError as exc:
                log.warning("Failed to parse YAML frontmatter: %s", exc)
    return {}, content.strip()


def format_draft_note(metadata: Dict[str, Any], body: str) -> str:
    """Format metadata and body into an Obsidian markdown document with YAML frontmatter."""
    fm = yaml.dump(metadata, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{fm}\n---\n\n{body.strip()}\n"


def write_draft_note(file_path: Path, metadata: Dict[str, Any], body: str) -> Path:
    """Write draft note with frontmatter to the designated file path."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(format_draft_note(metadata, body), encoding="utf-8")
    return file_path


def update_draft_note_frontmatter(file_path: Path, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update frontmatter fields in a draft note while preserving the body."""
    if not file_path.exists():
        return {}
    content = file_path.read_text(encoding="utf-8")
    metadata, body = parse_draft_note(content)
    metadata.update(updates)
    file_path.write_text(format_draft_note(metadata, body), encoding="utf-8")
    return metadata


def find_draft_note(issues_dir: Path, issue_number: Optional[int] = None) -> Optional[Path]:
    """Find a draft note by issue number or latest pending file."""
    if not issues_dir.exists():
        return None

    if issue_number is not None:
        matches = list(issues_dir.glob(f"Bacon Bento Vol {issue_number} - *.md"))
        if matches:
            return sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        return None

    # Search for latest pending draft
    all_files = sorted(issues_dir.glob("Bacon Bento Vol *.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in all_files:
        try:
            meta, _ = parse_draft_note(p.read_text(encoding="utf-8"))
            if meta.get("status") == "pending":
                return p
        except Exception:
            continue

    return all_files[0] if all_files else None
