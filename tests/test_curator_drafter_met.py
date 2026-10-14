"""Unit tests for Met API, LLM client, Curator, Drafter, and DB draft operations."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.config import Source
from src.curator import CurationDecision, CurationResult, curate_candidates
from src.db import Database
from src.drafter import draft_issue_package
from src.llm import LLMError, OpenRouterClient
from src.met import MetArtwork, fetch_met_artwork
from src.parser import Entry


def test_db_drafts_and_met(tmp_path):
    db_file = tmp_path / "test.db"
    db = Database(str(db_file))

    # Met tracking
    assert not db.is_met_seen(12345)
    db.mark_met_seen(12345, "Great Wave")
    assert db.is_met_seen(12345)

    # Draft lifecycle
    payload = {"issue_number": 1, "issue_html": "<b>Test Issue</b>", "selected_entries": []}
    draft_id = db.save_draft(payload)
    assert draft_id == 1

    pending = db.get_draft()
    assert pending is not None
    assert pending["issue_id"] == 1
    assert pending["status"] == "pending"
    assert pending["issue_html"] == "<b>Test Issue</b>"

    # Approve
    approved = db.approve_draft(1)
    assert approved["status"] == "approved"

    # No more pending
    assert db.get_draft() is None

    # Get by specific id
    draft_1 = db.get_draft(1)
    assert draft_1["status"] == "approved"
    db.close()


def test_llm_client_complete():
    client = OpenRouterClient(api_key="mock-key", default_model="mock-model")
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Generated test content"}}]
        }
        mock_post.return_value = mock_resp

        res = client.complete([{"role": "user", "content": "hello"}])
        assert res == "Generated test content"
        assert mock_post.called


def test_llm_client_retries_on_502():
    client = OpenRouterClient(api_key="mock-key", default_model="mock-model")
    with patch("requests.post") as mock_post, patch("time.sleep"):
        err_resp = MagicMock()
        err_resp.status_code = 502
        err_resp.text = "Bad Gateway"

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {
            "choices": [{"message": {"content": "Success after retry"}}]
        }

        mock_post.side_effect = [err_resp, ok_resp]

        res = client.complete([{"role": "user", "content": "retry test"}])
        assert res == "Success after retry"
        assert mock_post.call_count == 2


def test_met_artwork_fetch():
    source = Source(
        id="met-collection",
        name="The Met",
        type="api",
        url="https://met.org",
        endpoint="https://met.org/api",
        config={"department_ids": [11], "require_highlight": True},
    )

    with patch("requests.get") as mock_get:
        search_resp = MagicMock()
        search_resp.status_code = 200
        search_resp.json.return_value = {"objectIDs": [101, 102]}

        obj_resp = MagicMock()
        obj_resp.status_code = 200
        obj_resp.json.return_value = {
            "title": "Water Lilies",
            "artistDisplayName": "Claude Monet",
            "objectDate": "1914",
            "medium": "Oil on canvas",
            "department": "European Paintings",
            "primaryImage": "https://met.org/img.jpg",
            "isPublicDomain": True,
            "objectURL": "https://met.org/art/101",
        }

        mock_get.side_effect = [search_resp, obj_resp]

        art = fetch_met_artwork(source, is_seen=lambda oid: False)
        assert art is not None
        assert art.title == "Water Lilies"
        assert art.artist == "Claude Monet"
        assert art.image_url == "https://met.org/img.jpg"


def test_curate_candidates():
    candidates = [
        Entry(id="e1", feed_url="", source_tag="Aeon", title="Essay 1", link="http://1", summary="Sum 1", published=100.0, source_name="Aeon", course="anchor"),
        Entry(id="e2", feed_url="", source_tag="Coda", title="Essay 2", link="http://2", summary="Sum 2", published=100.0, source_name="Coda Story", course="lens"),
    ]

    mock_client = MagicMock()
    mock_client.complete.return_value = json.dumps({
        "selections": {
            "anchor": {"selected_id": "e1", "rationale": "Deep philosophical interiority", "rejected_notes": []},
            "lens": {"selected_id": "e2", "rationale": "Thematic reporting", "rejected_notes": []},
            "craft": {"selected_id": None, "rationale": "", "rejected_notes": []},
            "garnish": {"selected_id": None, "rationale": "", "rejected_notes": []},
        }
    })

    result = curate_candidates(candidates, mock_client)
    assert len(result.selected_entries) == 2
    assert result.decisions["anchor"].entry.id == "e1"
    assert result.decisions["lens"].entry.id == "e2"
    assert result.decisions["craft"].entry is None
    assert result.decisions["garnish"].entry is None


def test_curate_candidates_with_jev():
    candidates = [
        Entry(id="e1", feed_url="", source_tag="Aeon", title="Essay 1", link="http://1", summary="Sum 1", published=100.0, source_name="Aeon", course="anchor"),
        Entry(id="e2", feed_url="", source_tag="Coda", title="Essay 2", link="http://2", summary="Sum 2", published=100.0, source_name="Coda Story", course="lens"),
    ]

    mock_client = MagicMock()
    mock_client.decide.return_value = {
        "anchor": {"type": "choice", "choice": "e1", "confidence": 0.95},
        "lens": {"type": "choice", "choice": "none_worthy", "confidence": 0.88},
    }

    result = curate_candidates(candidates, mock_client, model="typesafe/jev-1.13")
    assert len(result.selected_entries) == 1
    assert result.decisions["anchor"].entry.id == "e1"
    assert result.decisions["lens"].entry is None
    assert "95.0%" in result.decisions["anchor"].rationale


def test_draft_issue_package():
    entry = Entry(id="e1", feed_url="", source_tag="Aeon", title="Essay 1", link="http://1", summary="Sum 1", published=100.0, source_name="Aeon", course="anchor")
    curation = CurationResult(
        decisions={
            "anchor": CurationDecision(course="anchor", entry=entry, rationale="Strong fit"),
            "lens": CurationDecision(course="lens", entry=None, rationale=""),
        },
        selected_entries=[entry],
    )
    met_art = MetArtwork(
        object_id=99,
        title="Print",
        artist="Artist",
        date="1900",
        medium="Woodblock",
        department="Asian Art",
        object_url="http://met/99",
        image_url="http://met/img.jpg",
    )

    mock_client = MagicMock()
    mock_client.complete.return_value = "🍱 <b>Bacon's Bento · Issue #1</b>\n\nIntro text\n\n⚓ <b>The Anchor</b>\nTitle"

    package = draft_issue_package(curation, met_art, issue_number=1, client=mock_client)
    assert package.issue_number == 1
    assert "Bacon's Bento" in package.issue_html
    assert "DRAFT REVIEW" in package.review_summary_html
    assert "Anchor:" in package.review_summary_html
