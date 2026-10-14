"""Telegram HTML message templating."""
from __future__ import annotations

import html
import re

from .parser import Entry

TG_LIMIT = 4096


def _hashtag(tag: str) -> str:
    return "#" + (re.sub(r"[^0-9A-Za-z_]", "", tag) or "Bento")


def format_entry(entry: Entry) -> str:
    link = html.escape(entry.link, quote=True)
    title = html.escape(entry.title)
    parts = [f'🍱 <b><a href="{link}">{title}</a></b>']
    if entry.summary:
        parts.append(html.escape(entry.summary))
    parts.append(f'<i>{html.escape(_hashtag(entry.source_tag))}</i> · <a href="{link}">Read</a>')
    msg = "\n\n".join(parts)
    return msg[:TG_LIMIT]
