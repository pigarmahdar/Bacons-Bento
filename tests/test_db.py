from src.db import Database, entry_id, normalize_url


def test_normalize_strips_tracking_and_slash():
    a = normalize_url("https://Example.com/post/?utm_source=x&id=1&fbclid=z#frag")
    assert a == "https://example.com/post?id=1"


def test_entry_id_stable_across_tracking_params():
    assert entry_id(None, "https://a.com/x?utm_medium=1") == entry_id(None, "https://a.com/x")


def test_guid_preferred():
    assert entry_id("guid-1", "https://a.com/1") == entry_id("guid-1", "https://b.com/2")


def test_mark_and_seen():
    db = Database(":memory:")
    eid = entry_id(None, "https://a.com/x")
    assert not db.is_seen(eid)
    db.mark_seen(eid, "f", "t", "https://a.com/x", posted=True)
    assert db.is_seen(eid)
    db.mark_seen(eid, "f", "t", "https://a.com/x", posted=True)  # idempotent


def test_prune():
    db = Database(":memory:")
    db.mark_seen("old", "f", "t", "l", posted=True)
    db.conn.execute("UPDATE seen SET first_seen = datetime('now','-400 days')")
    db.mark_seen("new", "f", "t", "l", posted=True)
    assert db.prune(180) == 1
    assert db.is_seen("new") and not db.is_seen("old")


def test_save_and_update_draft():
    db = Database(":memory:")
    draft_id = db.save_draft({"issue_number": 1, "issue_html": "<b>V1</b>"})
    d1 = db.get_draft(draft_id)
    assert d1["issue_html"] == "<b>V1</b>"

    ok = db.update_draft(draft_id, {"issue_number": 1, "issue_html": "<b>V2</b>"})
    assert ok is True
    d2 = db.get_draft(draft_id)
    assert d2["issue_html"] == "<b>V2</b>"
