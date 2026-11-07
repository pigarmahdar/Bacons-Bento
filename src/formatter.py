"""Telegram HTML message templating."""
from __future__ import annotations

from html.parser import HTMLParser
import html
import re
from typing import Any, Optional

from .parser import Entry

TG_LIMIT = 4096
TG_CAPTION_LIMIT = 1024


def _hashtag(tag: str) -> str:
    return "#" + (re.sub(r"[^0-9A-Za-z_]", "", tag) or "Bento")


VALID_TG_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "span", "tg-spoiler", "a", "code", "pre", "blockquote"}


class _TelegramHTMLValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag not in VALID_TG_TAGS:
            self.errors.append(f"Disallowed HTML tag: <{tag}>")
            return
        if tag == "a":
            href = dict(attrs).get("href")
            if not href:
                self.errors.append("<a href='...'> tag missing 'href' attribute")
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag not in VALID_TG_TAGS:
            return
        if not self.stack:
            self.errors.append(f"Unexpected closing tag </{tag}> with no matching open tag")
        elif self.stack[-1] != tag:
            self.errors.append(f"Mismatched closing tag </{tag}>; expected </{self.stack[-1]}>")
            if tag in self.stack:
                while self.stack and self.stack[-1] != tag:
                    self.stack.pop()
                if self.stack:
                    self.stack.pop()
        else:
            self.stack.pop()

    def close(self) -> None:
        super().close()
        for unclosed in reversed(self.stack):
            self.errors.append(f"Unclosed HTML tag: <{unclosed}>")


def validate_telegram_html(text: str, max_length: int = TG_LIMIT) -> list[str]:
    """Validate HTML tag nesting, allowed Telegram tags, markdown leaks, and length limits."""
    errors: list[str] = []
    if len(text) > max_length:
        errors.append(f"Length ({len(text)}) exceeds Telegram limit of {max_length} characters")

    # Guard against unclosed markdown tokens that did not convert
    if text.count("**") % 2 != 0:
        errors.append("Unclosed markdown bold delimiter '**'")
    if text.count("```") % 2 != 0:
        errors.append("Unclosed markdown code block delimiter '```'")
    elif text.count("`") % 2 != 0:
        errors.append("Unclosed markdown inline code delimiter '`'")

    validator = _TelegramHTMLValidator()
    try:
        validator.feed(text)
        validator.close()
    except Exception as exc:
        errors.append(f"HTML parsing error: {exc}")
    errors.extend(validator.errors)
    return errors


def format_met_caption(met: Any) -> str:
    """Format Met artwork metadata into a clean Telegram HTML caption."""
    if not met:
        return ""
    if isinstance(met, dict):
        title = met.get("title") or "Untitled"
        date = met.get("date") or "n.d."
        artist = met.get("artist") or "Unknown Artist"
        medium = met.get("medium") or ""
        department = met.get("department") or ""
        object_url = met.get("object_url") or ""
    else:
        title = getattr(met, "title", "") or "Untitled"
        date = getattr(met, "date", "") or "n.d."
        artist = getattr(met, "artist", "") or "Unknown Artist"
        medium = getattr(met, "medium", "") or ""
        department = getattr(met, "department", "") or ""
        object_url = getattr(met, "object_url", "") or ""

    parts = [
        f"🌳 <b>{title}</b> ({date})",
        f"<i>{artist}</i>" + (f" · {medium}" if medium else ""),
        f"{department}, <a href=\"{object_url}\">The Met Collection (CC0)</a>" if object_url else department,
    ]
    return "\n".join(p for p in parts if p)


def clean_telegram_html(text: str) -> str:
    """Sanitize and auto-balance HTML tags so Telegram Bot API never rejects with 400 Bad Request."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all(True):
        if tag.name not in VALID_TG_TAGS:
            tag.unwrap()
        elif tag.name == "a":
            href = tag.get("href")
            tag.attrs = {"href": href} if href else {}
        else:
            tag.attrs = {}
    return str(soup)


def markdown_to_telegram_html(text: str) -> str:
    """Normalize common Markdown markup into Telegram-safe HTML while preserving existing HTML tags."""
    # 1. Blockquotes: consecutive lines starting with >
    def _bq(m: re.Match) -> str:
        lines = [re.sub(r"^>\s?", "", line) for line in m.group(0).splitlines()]
        joined = "\n".join(lines)
        return f"<blockquote>{joined}</blockquote>"

    text = re.sub(r"(?:^>.*(?:\n|$))+", _bq, text, flags=re.MULTILINE)

    # 2. Markdown links: [label](url)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", r'<a href="\2">\1</a>', text)

    # 3. Bold: **text** or __text__
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_]+)__", r"<b>\1</b>", text)

    # 4. Italic: *text* or _text_ (excluding boundaries that look like words or URLs)
    text = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"<i>\1</i>", text)
    text = re.sub(r"(?<![_\w])_([^_\n]+)_(?![_\w])", r"<i>\1</i>", text)

    # 5. Inline code: `code`
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)

    # 6. Sanitize and auto-balance tags
    return clean_telegram_html(text)


def format_entry(entry: Entry) -> str:
    link = html.escape(entry.link, quote=True)
    title = html.escape(entry.title)
    parts = [f'🍱 <b><a href="{link}">{title}</a></b>']
    if entry.summary:
        parts.append(html.escape(entry.summary))
    parts.append(f'<i>{html.escape(_hashtag(entry.source_tag))}</i> · <a href="{link}">Read</a>')
    msg = "\n\n".join(parts)
    return msg[:TG_LIMIT]


def html_to_terminal(text: str) -> str:
    """Render Telegram HTML as readable ANSI-styled terminal text."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(text, "html.parser")

    # Format blockquotes
    for bq in soup.find_all("blockquote"):
        content = bq.get_text().strip()
        lines = [f"  │ \033[3m{line}\033[0m" for line in content.splitlines()]
        bq.replace_with("\n" + "\n".join(lines) + "\n")

    # Format links
    for a in soup.find_all("a"):
        href = a.get("href", "")
        label = a.get_text().strip()
        if href and label and href != label:
            a.replace_with(f"\033[4;36m{label}\033[0m (\033[2m{href}\033[0m)")
        elif href:
            a.replace_with(f"\033[4;36m{href}\033[0m")
        else:
            a.replace_with(label)

    # Format bold
    for b in soup.find_all(["b", "strong"]):
        b.replace_with(f"\033[1m{b.get_text()}\033[0m")

    # Format italics
    for i in soup.find_all(["i", "em"]):
        i.replace_with(f"\033[3m{i.get_text()}\033[0m")

    # Format inline code
    for c in soup.find_all(["code", "pre"]):
        c.replace_with(f"\033[7m {c.get_text()} \033[0m")

    return html.unescape(soup.get_text())


def format_terminal_box(title: str, content: str, width: int = 76) -> str:
    """Wrap content in a clean unicode box."""
    top = f"┌─ \033[1m{title}\033[0m " + "─" * max(0, width - len(title) - 5) + "┐"
    bottom = "└" + "─" * (width - 1) + "┘"
    return f"{top}\n{content}\n{bottom}"

