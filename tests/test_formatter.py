from src.formatter import (
    TG_CAPTION_LIMIT,
    TG_LIMIT,
    format_entry,
    format_met_caption,
    markdown_to_telegram_html,
    validate_telegram_html,
)
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


def test_validate_telegram_html_clean():
    clean_text = "<b>Bold</b> and <i>italic</i> with <a href='https://example.com'>link</a>."
    assert validate_telegram_html(clean_text) == []


def test_validate_telegram_html_limits():
    assert validate_telegram_html("a" * (TG_LIMIT + 1)) != []
    assert validate_telegram_html("a" * (TG_CAPTION_LIMIT + 1), max_length=TG_CAPTION_LIMIT) != []
    assert validate_telegram_html("a" * TG_CAPTION_LIMIT, max_length=TG_CAPTION_LIMIT) == []


def test_validate_telegram_html_nesting():
    # Unclosed tag
    errs = validate_telegram_html("<b>Bold text")
    assert any("Unclosed HTML tag: <b>" in e for e in errs)

    # Mismatched tag
    errs = validate_telegram_html("<b><i>Bold italic</b></i>")
    assert any("Mismatched closing tag </b>" in e for e in errs)

    # Unexpected closing tag
    errs = validate_telegram_html("Hello</b>")
    assert any("Unexpected closing tag </b>" in e for e in errs)

    # Disallowed tag
    errs = validate_telegram_html("<div>Hello</div>")
    assert any("Disallowed HTML tag: <div>" in e for e in errs)

    # Unclosed markdown delimiter
    errs = validate_telegram_html("Here is **unfinished bold text")
    assert any("Unclosed markdown bold delimiter" in e for e in errs)


def test_format_met_caption():
    met = {
        "title": "Starry Night",
        "date": "1889",
        "artist": "Vincent van Gogh",
        "medium": "Oil on canvas",
        "department": "European Paintings",
        "object_url": "https://example.com/art",
    }
    caption = format_met_caption(met)
    assert "<b>Starry Night</b>" in caption
    assert "<i>Vincent van Gogh</i>" in caption
    assert validate_telegram_html(caption, max_length=TG_CAPTION_LIMIT) == []


