"""AI Decision Engine for evaluating candidate articles against the Bento Manifesto."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .llm import LLMError, OpenRouterClient
from .parser import Entry

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class CurationDecision:
    course: str
    entry: Optional[Entry]
    rationale: str
    rejected_reasons: List[str] = field(default_factory=list)


@dataclass
class CurationResult:
    decisions: Dict[str, CurationDecision]
    selected_entries: List[Entry]


def load_manifesto_text() -> str:
    path = ROOT / "MANIFESTO.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _curate_with_jev(
    candidates: List[Entry],
    client: OpenRouterClient,
    model: str,
    manifesto: str,
) -> CurationResult:
    """Use TypeSafe Jev Decision API (e.g. typesafe/jev-1.13) to rank and select candidates."""
    by_course: Dict[str, List[Entry]] = {"anchor": [], "lens": [], "craft": [], "garnish": []}
    entry_map: Dict[str, Entry] = {}

    for e in candidates:
        c = e.course.lower()
        if c in by_course:
            by_course[c].append(e)
            entry_map[e.id] = e

    questions = {}
    for course_key, entries in by_course.items():
        if not entries:
            continue
        criteria: Dict[str, str] = {}
        for e in entries[:25]:  # Jev criteria limit
            criteria[e.id] = f"{e.title} ({e.source_name}): {e.summary[:140]}"
        criteria["none_worthy"] = "None of these candidates meet the Bento Manifesto standards (Silence beats noise)."

        questions[course_key] = {
            "type": "choice",
            "instructions": f"Select the single best article for '{course_key.title()}' course satisfying the Bento Manifesto (or 'none_worthy' if none meet the bar).",
            "criteria": criteria,
        }

    if not questions:
        return CurationResult(decisions={}, selected_entries=[])

    state = f"Bento Manifesto Curation:\n{manifesto[:1500]}"
    try:
        answers = client.decide(state=state, questions=questions, model=model)
    except Exception as exc:
        log.error("Jev decision call failed: %s", exc)
        return CurationResult(decisions={}, selected_entries=[])

    decisions: Dict[str, CurationDecision] = {}
    selected_entries: List[Entry] = []
    seen_sources = set()

    for course_key in ("anchor", "lens", "craft", "garnish"):
        ans = answers.get(course_key, {})
        sel_id = ans.get("choice")
        conf = ans.get("confidence", 0.0)
        entry = entry_map.get(sel_id) if sel_id and sel_id != "none_worthy" else None

        if entry:
            source_key = (entry.source_name or entry.source_tag).lower()
            if source_key in seen_sources:
                log.info("Source collision for '%s'; skipping duplicate in %s", entry.source_name, course_key)
                entry = None
            else:
                seen_sources.add(source_key)

        if entry:
            selected_entries.append(entry)

        rationale = f"Selected by {model} with {conf*100:.1f}% confidence against criteria." if entry else "No candidate met the bar."
        decisions[course_key] = CurationDecision(
            course=course_key,
            entry=entry,
            rationale=rationale,
            rejected_reasons=[],
        )

    return CurationResult(decisions=decisions, selected_entries=selected_entries)


def curate_candidates(
    candidates: List[Entry],
    client: OpenRouterClient,
    model: Optional[str] = None,
) -> CurationResult:
    """Evaluate candidate entries against MANIFESTO.md principles using the Decision Model."""
    if not candidates:
        return CurationResult(decisions={}, selected_entries=[])

    target_model = model or client.default_model
    manifesto = load_manifesto_text()

    if "jev" in target_model.lower():
        return _curate_with_jev(candidates, client, target_model, manifesto)

    # General chat completions fallback
    by_course: Dict[str, List[dict]] = {"anchor": [], "lens": [], "craft": [], "garnish": []}
    entry_map: Dict[str, Entry] = {}
    for e in candidates:
        course = e.course.lower()
        if course in by_course:
            by_course[course].append({
                "id": e.id,
                "title": e.title,
                "source": e.source_name or e.source_tag,
                "link": e.link,
                "summary": e.summary[:240],
            })
            entry_map[e.id] = e

    prompt = f"""You are the curatorial intelligence for Bacon's Bento (@baconbento).
Your job is to strictly evaluate candidate articles against our editorial standards and choose the single best piece for each course.

=== THE BENTO MANIFESTO ===
{manifesto}

=== CANDIDATE POOL BY COURSE ===
{json.dumps(by_course, indent=2)}

=== YOUR INSTRUCTIONS ===
1. Evaluate candidates against the 4 Pillars of Taste and the Anti-Pillars.
2. For each course ("anchor", "lens", "craft", "garnish"):
   - Pick at most ONE article id that best exemplifies the course and meets the litmus test.
   - If NONE of the candidates meet our high bar, select null.
   - At most ONE article from any single source across the final selection.
3. Provide your rationale explaining which pillar is satisfied and why it stood out.

Respond ONLY with a valid JSON object matching this schema:
{{
  "selections": {{
    "anchor": {{ "selected_id": "<entry_id or null>", "rationale": "<...>" }},
    "lens": {{ "selected_id": "<entry_id or null>", "rationale": "<...>" }},
    "craft": {{ "selected_id": "<entry_id or null>", "rationale": "<...>" }},
    "garnish": {{ "selected_id": "<entry_id or null>", "rationale": "<...>" }}
  }}
}}
"""

    messages = [
        {"role": "system", "content": "You are a meticulous, high-taste literary and philosophical curator."},
        {"role": "user", "content": prompt},
    ]

    try:
        raw_resp = client.complete(messages, model=target_model, temperature=0.3, json_mode=True)
        clean_json = raw_resp.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
        parsed = json.loads(clean_json.strip())
        selections = parsed.get("selections", {})
    except Exception as exc:
        log.error("Curation decision model failed: %s; falling back to empty selection", exc)
        return CurationResult(decisions={}, selected_entries=[])

    decisions: Dict[str, CurationDecision] = {}
    selected_entries: List[Entry] = []
    seen_sources = set()

    for course_key in ("anchor", "lens", "craft", "garnish"):
        c_data = selections.get(course_key) or {}
        sel_id = c_data.get("selected_id")
        entry = entry_map.get(sel_id) if sel_id else None

        if entry:
            source_key = (entry.source_name or entry.source_tag).lower()
            if source_key in seen_sources:
                log.info("Source collision for '%s'; skipping duplicate source in %s", entry.source_name, course_key)
                entry = None
            else:
                seen_sources.add(source_key)

        if entry:
            selected_entries.append(entry)

        decisions[course_key] = CurationDecision(
            course=course_key,
            entry=entry,
            rationale=c_data.get("rationale", ""),
            rejected_reasons=c_data.get("rejected_notes", []),
        )

    return CurationResult(decisions=decisions, selected_entries=selected_entries)
