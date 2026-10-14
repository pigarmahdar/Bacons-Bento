from src.config import Feed
from src.parser import clean_text, parse_feed_bytes

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
<item><title>Hello &amp; welcome</title><link>https://a.com/1?utm_source=x</link>
<guid>g1</guid><pubDate>Mon, 13 Oct 2026 08:00:00 GMT</pubDate>
<description>&lt;p&gt;Some &lt;b&gt;bold&lt;/b&gt;   text&lt;/p&gt;</description></item>
<item><title></title><link>https://a.com/2</link></item>
<item><title>No link</title></item>
</channel></rss>"""

FEED = Feed("T", "https://a.com/feed", "Tee")


def test_parse_skips_invalid_and_sanitizes():
    entries = parse_feed_bytes(RSS, FEED)
    assert len(entries) == 1
    e = entries[0]
    assert e.title == "Hello & welcome"
    assert e.summary == "Some bold text"
    assert e.source_tag == "Tee"
    assert e.published > 0


def test_truncate_at_word_boundary():
    out = clean_text("word " * 100, 20)
    assert out.endswith("…") and len(out) <= 21 and "wor…" not in out
