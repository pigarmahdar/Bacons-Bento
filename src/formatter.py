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

