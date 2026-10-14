"""Sentence Package Drafter: produces the unified issue and review package."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from .curator import CurationResult
from .llm import OpenRouterClient
from .met import MetArtwork

log = logging.getLogger(__name__)

TG_LIMIT = 4096


@dataclass
class DraftPackage:
    issue_number: int
    issue_html: str
    review_summary_html: str
    met_artwork: Optional[MetArtwork]


def draft_issue_package(
    curation: CurationResult,
    met_artwork: Optional[MetArtwork],
    issue_number: int,
    client: OpenRouterClient,
    model: Optional[str] = None,
) -> DraftPackage:
    """Draft the unified Bento issue and the private admin review summary."""
    course_items = {}
    for course_key, dec in curation.decisions.items():
        if dec.entry:
            course_items[course_key] = {
                "course": course_key,
                "source": dec.entry.source_name or dec.entry.source_tag,
                "title": dec.entry.title,
                "link": dec.entry.link,
                "summary": dec.entry.summary,
                "editorial_rationale": dec.rationale,
            }

    if met_artwork:
        course_items["visual_garnish"] = {
            "course": "visual_garnish",
            "source": "The Metropolitan Museum of Art",
            "artwork_name": met_artwork.title,
            "year": met_artwork.date or "n.d.",
            "artist": met_artwork.artist or "Unknown Artist",
            "medium": met_artwork.medium,
            "collection_info": f"{met_artwork.department}, The Met Collection (CC0)",
            "link": met_artwork.object_url,
            "image_url": met_artwork.image_url,
        }

    prompt = f"""You are the master drafter for Bacon's Bento (@baconbento), a personal digital garden of curious intersections, slow ideas, and quiet craft.

Here are the selected pieces for this week's Bento Plate (Issue #{issue_number}):
{json.dumps(course_items, indent=2)}

Format this as a weekly Telegram issue using clean Telegram HTML (<b>, <i>, <a href="...">).

Editorial Guidelines:
1. Header: 🍱 <b>Bacon's Bento · Issue #{issue_number}</b>
2. Thematic Synthesis Intro: Write an insightful, cohesive 2-4 sentence opening synthesis that weaves together the subtle nuances, common threads, and tensions connecting these selections. (Avoid meta-commentary like "This week we explore"; articulate the conceptual undercurrent linking them together).
3. The Courses (only include courses that have a selection):
   - ⚓ <b>The Anchor</b> (Philosophy & Meaning)
   - 👁 <b>The Lens</b> (Narrative Investigation)
   - 🩺 <b>The Craft</b> (Concepts & Science)
   - 🃏 <b>The Garnish</b> (Curiosities & Oddities)
   - 🌳 <b>Visual Garnish</b> (The Met Open Access)
   
   For Reading Courses (Anchor, Lens, Craft, Garnish):
   - Icon + Course Name in bold
   - Linked Title and Source in italics: <i><a href="[URL]">[Title]</a> — [Source]</i>
   - 1-2 sentence thoughtful commentary/hook reflecting Bento's aesthetic (patience, craft, defamiliarization).

   For 🌳 <b>Visual Garnish</b> (The Met Open Access):
   - Must use this standardized layout:
     🌳 <b>Visual Garnish</b>
     <i><a href="[URL]">[Artwork Name] ([Year])</a></i>
     <i>[Artist] · [Medium] · [Department], The Met Collection (CC0)</i>
     1 sentence: quiet atmospheric observation linking light, craft, or form.

4. Quiet sign-off:
   — <i>slow ideas, quiet craft, curious intersections.</i>

Keep it strictly under 2400 characters. Return ONLY the final formatted HTML message.
"""

    messages = [
        {"role": "system", "content": "You are a master essayist and contemplative editor."},
        {"role": "user", "content": prompt},
    ]

    issue_html = client.complete(messages, model=model, temperature=0.7)
    issue_html = issue_html.strip()
    if issue_html.startswith("```html"):
        issue_html = issue_html[7:]
    if issue_html.endswith("```"):
        issue_html = issue_html[:-3]
    issue_html = issue_html.strip()[:TG_LIMIT]

    # Build the private review summary for Bacon
    review_lines = [
        f"📝 <b>BACON'S BENTO · DRAFT REVIEW (Issue #{issue_number})</b>\n",
        "<b>Curatorial Decisions & Rationales:</b>",
    ]
    for course_key, dec in curation.decisions.items():
        if dec.entry:
            review_lines.append(f"• <b>{course_key.title()}:</b> <i>{dec.entry.title}</i> ({dec.entry.source_name})")
            if dec.rationale:
                review_lines.append(f"  ↳ <i>{dec.rationale}</i>")
        else:
            review_lines.append(f"• <b>{course_key.title()}:</b> <i>[Empty - No candidate met the bar]</i>")

    if met_artwork:
        review_lines.append(f"• <b>Visual Garnish:</b> <i>{met_artwork.title}</i> by {met_artwork.artist} ({met_artwork.department})")

    review_lines.append("\n<b>Preview of Dispatched Issue:</b>\n" + "—" * 20 + "\n")
    review_lines.append(issue_html)
    review_summary_html = "\n".join(review_lines)[:TG_LIMIT]

    return DraftPackage(
        issue_number=issue_number,
        issue_html=issue_html,
        review_summary_html=review_summary_html,
        met_artwork=met_artwork,
    )
