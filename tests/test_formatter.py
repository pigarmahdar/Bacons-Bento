from src.formatter import TG_LIMIT, format_entry
from src.parser import Entry


def make(**kw):
    base = dict(id="i", feed_url="f", source_tag="Hacker News", title="A <b> & B",
                link='https://a.com/x?a=1&b="2"', summary="sum <x>", published=0.0)
    base.update(kw)
    return Entry(**base)


def test_escaping():
    out = format_entry(make())
    assert "A &lt;b&gt; &amp; B" in out
    assert "&quot;2&quot;" in out and "sum &lt;x&gt;" in out
    assert "#HackerNews" in out


def test_length_cap():
    assert len(format_entry(make(summary="x" * 10000))) <= TG_LIMIT


def test_no_summary():
    assert "\n\n\n" not in format_entry(make(summary=""))
