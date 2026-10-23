from src.formatter import TG_LIMIT, format_entry, markdown_to_telegram_html
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


def test_markdown_to_telegram_html():
    md = (
        "🍱 <b>Bacon's Bento · Issue #1</b>\n\n"
        "Opening with **bold statement** and *italic thought*.\n"
        "Here is a [link to essay](https://example.com/essay).\n"
        "> A quiet observation.\n"
        "> Second line.\n"
        "And some `inline code`.\n"
    )
    result = markdown_to_telegram_html(md)
    assert "<b>bold statement</b>" in result
    assert "<i>italic thought</i>" in result
    assert '<a href="https://example.com/essay">link to essay</a>' in result
    assert "<blockquote>A quiet observation.\nSecond line.</blockquote>" in result
    assert "<code>inline code</code>" in result
    assert "🍱 <b>Bacon's Bento · Issue #1</b>" in result

