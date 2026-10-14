from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from src import cli
from src.formatter import format_terminal_box, html_to_terminal


def test_html_to_terminal():
    raw_html = (
        '<b>Title</b> and <i>italic</i> and <a href="https://example.com">Link</a>\n'
        '<blockquote>Quoted thought</blockquote>'
    )
    rendered = html_to_terminal(raw_html)
    assert "\033[1mTitle\033[0m" in rendered
    assert "\033[3mitalic\033[0m" in rendered
    assert "https://example.com" in rendered
    assert "Quoted thought" in rendered
    assert "│" in rendered


def test_format_terminal_box():
    box = format_terminal_box("TEST TITLE", "Line 1\nLine 2")
    assert "TEST TITLE" in box
    assert "Line 1" in box
    assert "Line 2" in box
    assert box.startswith("┌─")
    assert box.endswith("┘")


def test_cli_parser_subcommands():
    parser = cli.build_parser()

    # new / draft
    args = parser.parse_args(["new", "--dry-run", "--no-notify"])
    assert args.subcommand == "new"
    assert args.dry_run is True
    assert args.no_notify is True

    args_draft = parser.parse_args(["draft"])
    assert args_draft.subcommand == "draft"

    # preview / show
    args_prev = parser.parse_args(["preview", "--issue-id", "42"])
    assert args_prev.subcommand == "preview"
    assert args_prev.issue_id == 42

    args_show = parser.parse_args(["show"])
    assert args_show.subcommand == "show"
    assert args_show.issue_id is None

    # publish / approve
    args_pub = parser.parse_args(["publish", "-y"])
    assert args_pub.subcommand == "publish"
    assert args_pub.yes is True

    args_app = parser.parse_args(["approve", "--issue-id", "5"])
    assert args_app.subcommand == "approve"
    assert args_app.issue_id == 5

    # status & bootstrap
    assert parser.parse_args(["status"]).subcommand == "status"
    assert parser.parse_args(["bootstrap"]).subcommand == "bootstrap"


def test_cmd_status(monkeypatch, capsys):
    mock_db = MagicMock()
    mock_db.get_hopper_stats.return_value = {
        "seen_total": 42,
        "posted_total": 10,
        "met_seen_total": 2,
        "published_count": 2,
        "last_published": {"issue_number": 2, "created_at": "2026-10-14"},
        "pending_draft": None,
    }
    monkeypatch.setattr(cli, "load_settings", lambda **kw: MagicMock(db_path=":memory:"))
    monkeypatch.setattr(cli, "Database", lambda path: mock_db)
    monkeypatch.setattr(cli, "load_feeds", lambda: [MagicMock(), MagicMock()])

    rc = cli.cmd_status(argparse.Namespace())
    assert rc == 0
    captured = capsys.readouterr().out
    assert "Active Feeds in Registry :" in captured
    assert "Total Articles Ingested  : 42" in captured
    assert "Articles Published       : 10" in captured
    assert "Published Issues Total   :" in captured
    assert "None (ready for new issue" in captured



def test_cmd_preview_not_found(monkeypatch, capsys):
    mock_db = MagicMock()
    mock_db.get_draft.return_value = None
    monkeypatch.setattr(cli, "load_settings", lambda **kw: MagicMock(db_path=":memory:"))
    monkeypatch.setattr(cli, "Database", lambda path: mock_db)

    rc = cli.cmd_preview(argparse.Namespace(issue_id=None))
    assert rc == 1
    assert "No pending draft found" in capsys.readouterr().out


def test_cmd_preview_found(monkeypatch, capsys):
    mock_db = MagicMock()
    mock_db.get_draft.return_value = {
        "issue_id": 99,
        "issue_number": 1,
        "status": "pending",
        "created_at": "2026-10-14",
        "issue_html": "<b>Issue #1</b>",
        "met_artwork": {
            "title": "Ancient Bowl",
            "artist": "Unknown",
            "department": "Arts of the Americas",
            "image_url": "https://example.com/art.jpg",
            "object_url": "https://metmuseum.org/123",
        },
    }
    monkeypatch.setattr(cli, "load_settings", lambda **kw: MagicMock(db_path=":memory:"))
    monkeypatch.setattr(cli, "Database", lambda path: mock_db)

    rc = cli.cmd_preview(argparse.Namespace(issue_id=99))
    assert rc == 0
    captured = capsys.readouterr().out
    assert "Draft Issue #1" in captured
    assert "Ancient Bowl" in captured
    assert "Ready to publish?" in captured


def test_cmd_publish_success(monkeypatch, capsys):
    mock_db = MagicMock()
    mock_db.get_draft.return_value = {
        "issue_id": 1,
        "issue_number": 1,
        "status": "pending",
        "issue_html": "<b>Bento Issue 1</b>",
        "selected_entries": [{"id": "e1", "feed_url": "f1", "title": "t1", "link": "l1"}],
        "met_artwork": {
            "object_id": 100,
            "title": "Gold Mask",
            "artist": "Moche",
            "medium": "Gold",
            "department": "Americas",
            "object_url": "https://met.org/100",
            "image_url": "https://met.org/100.jpg",
        },
    }
    mock_tg = MagicMock()
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda **kw: MagicMock(db_path=":memory:", bot_token="TOKEN", chat_id="@baconbento", admin_chat_id="ADMIN"),
    )
    monkeypatch.setattr(cli, "Database", lambda path: mock_db)
    monkeypatch.setattr(cli, "TelegramClient", lambda token, chat_id: mock_tg)

    rc = cli.cmd_publish(argparse.Namespace(issue_id=1, yes=True))
    assert rc == 0
    mock_tg.send.assert_any_call("<b>Bento Issue 1</b>", chat_id="@baconbento")
    mock_tg.send_photo.assert_called_once()
    mock_db.mark_seen.assert_called_once_with("e1", "f1", "t1", "l1", posted=True)
    mock_db.mark_met_seen.assert_called_once_with(100, "Gold Mask")
    mock_db.approve_draft.assert_called_once_with(1)
    assert "successfully approved and broadcast" in capsys.readouterr().out
