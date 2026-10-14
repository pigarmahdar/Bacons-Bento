"""Telegram HTML message templating."""
from __future__ import annotations

import html
import re

from .parser import Entry

TG_LIMIT = 4096


def _hashtag(tag: str) -> str:
    return "#" + (re.sub(r"[^0-9A-Za-z_]", "", tag) or "Bento")


VALID_TG_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "span", "tg-spoiler", "a", "code", "pre", "blockquote"}


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


def format_entry(entry: Entry) -> str:
    link = html.escape(entry.link, quote=True)
    title = html.escape(entry.title)
    parts = [f'🍱 <b><a href="{link}">{title}</a></b>']
    if entry.summary:
        parts.append(html.escape(entry.summary))
    parts.append(f'<i>{html.escape(_hashtag(entry.source_tag))}</i> · <a href="{link}">Read</a>')
    msg = "\n\n".join(parts)
    return msg[:TG_LIMIT]
