from pathlib import Path
import pytest
from src.config import load_registry, load_feeds, Source

ROOT = Path(__file__).resolve().parent.parent


def test_load_registry_parses_yaml():
    registry_path = ROOT / "config" / "registry.yaml"
    sources = load_registry(registry_path)
    assert len(sources) >= 9  # enabled sources only

    # Check for specific courses and source types
    sources_by_id = {s.id: s for s in sources}
    assert "aeon" in sources_by_id
    assert "met-collection" in sources_by_id

    aeon = sources_by_id["aeon"]
    assert aeon.type == "rss"
    assert aeon.course == "anchor"
    assert "interdisciplinary" in aeon.pillars
    assert aeon.taste_profile.cognitive_load == "deep_dive"

    met = sources_by_id["met-collection"]
    assert met.type == "api"
    assert met.course == "visual_garnish"
    assert 6 in met.config["department_ids"]  # Asian Art
    assert 4 not in met.config["department_ids"]  # Arms and Armor excluded


def test_load_feeds_defaults_to_registry_rss():
    feeds = load_feeds()
    # Feeds should only include enabled RSS feeds (not API sources)
    assert len(feeds) >= 8
    names = [f.name for f in feeds]
    assert "Aeon" in names
    assert "Ocula" not in names  # removed from registry after feed audit
    assert "The Metropolitan Museum of Art" not in names  # API type is excluded from RSS feed list
