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


def _is_pantry(e: Entry) -> bool:
    return (e.source_name or e.source_tag).lower() == "chef's pantry"


def _first_available(entries: List[Entry], seen_sources: set[str]) -> Optional[Entry]:
    for e in entries:
        if (e.source_name or e.source_tag).lower() not in seen_sources:
            return e
    return None


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
        # Prioritize Chef's Pantry items so they aren't truncated by the 25-item limit
        ordered = sorted(entries, key=lambda e: (not _is_pantry(e)))
        by_course[course_key] = ordered
        criteria: Dict[str, str] = {}
        for e in ordered[:25]:  # Jev criteria limit
            criteria[e.id] = f"{e.title} ({e.source_name}): {e.summary[:140]}"

        questions[course_key] = {
            "type": "choice",
            "instructions": (
                f"Select the single best article for the '{course_key.title()}' course that best aligns with the Bento Manifesto. "
                "Give priority consideration to (Chef's Pantry) candidates as curator-saved reads, without overturning a clearly stronger fit, "
                "and select at most one (Chef's Pantry) item across the entire issue."
            ),
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
    seen_sources: set[str] = set()

    for course_key in ("anchor", "lens", "craft", "garnish"):
        ans = answers.get(course_key, {})
        sel_id = ans.get("choice")
        conf = ans.get("confidence", 0.0)
        entry = entry_map.get(sel_id) if sel_id else None

        if entry:
            source_key = (entry.source_name or entry.source_tag).lower()
            if source_key in seen_sources:
                log.info("Source collision for '%s'; falling back in %s", entry.source_name, course_key)
                entry = None

        if not entry and by_course[course_key]:
            entry = _first_available(by_course[course_key], seen_sources)

        if entry:
            seen_sources.add((entry.source_name or entry.source_tag).lower())
            selected_entries.append(entry)

        rationale = f"Selected by {model} with {conf*100:.1f}% confidence against criteria." if entry else "No candidates in pool."
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
    fallback_model: str = "xiaomi/mimo-v2.6-flash",
) -> CurationResult:
    """Evaluate candidate entries against MANIFESTO.md principles using the Decision Model."""
    if not candidates:
        return CurationResult(decisions={}, selected_entries=[])

    target_model = model or client.default_model
    manifesto = load_manifesto_text()

    if "jev" in target_model.lower():
        result = _curate_with_jev(candidates, client, target_model, manifesto)
        if result.selected_entries:
            return result
        log.warning("Jev decision returned 0 entries; falling back to completions with %s", fallback_model)
        target_model = fallback_model

    # General chat completions fallback
    by_course: Dict[str, List[dict]] = {"anchor": [], "lens": [], "craft": [], "garnish": []}
    by_course_entries: Dict[str, List[Entry]] = {"anchor": [], "lens": [], "craft": [], "garnish": []}
    entry_map: Dict[str, Entry] = {}
    for e in sorted(candidates, key=lambda x: (not _is_pantry(x))):
        course = e.course.lower()
        if course in by_course:
            by_course_entries[course].append(e)
            by_course[course].append({
                "id": e.id,
                "title": e.title,
                "source": e.source_name or e.source_tag,
                "link": e.link,
                "summary": e.summary[:240],
            })
            entry_map[e.id] = e

    prompt = f"""You are the curatorial intelligence for Bacon's Bento (@baconbento).
Your job is to evaluate candidate articles against our editorial standards and choose the single best piece for each course.

=== THE BENTO MANIFESTO ===
{manifesto}

=== CANDIDATE POOL BY COURSE ===
{json.dumps(by_course, indent=2)}

=== YOUR INSTRUCTIONS ===
1. Evaluate candidates against the 4 Pillars of Taste.
2. For each course ("anchor", "lens", "craft", "garnish"):
   - Always pick the single best available article id for every course that has candidates (only return null if the course's candidate list is empty).
   - Give priority consideration to "Chef's Pantry" candidates (personally saved by the curator), without overturning a clearly stronger candidate.
   - Select at most ONE article from any single source (including at most ONE "Chef's Pantry" item) across the entire issue.
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
        log.error("Curation decision model failed: %s; falling back to available candidates", exc)
        selections = {}

    decisions: Dict[str, CurationDecision] = {}
    selected_entries: List[Entry] = []
    seen_sources: set[str] = set()

    for course_key in ("anchor", "lens", "craft", "garnish"):
        c_data = selections.get(course_key) or {}
        sel_id = c_data.get("selected_id")
        entry = entry_map.get(sel_id) if sel_id else None

        if entry:
            source_key = (entry.source_name or entry.source_tag).lower()
            if source_key in seen_sources:
                log.info("Source collision for '%s'; skipping duplicate source in %s", entry.source_name, course_key)
                entry = None

        if not entry and by_course_entries[course_key]:
            entry = _first_available(by_course_entries[course_key], seen_sources)

        if entry:
            seen_sources.add((entry.source_name or entry.source_tag).lower())
            selected_entries.append(entry)

        decisions[course_key] = CurationDecision(
            course=course_key,
            entry=entry,
            rationale=c_data.get("rationale", ""),
            rejected_reasons=c_data.get("rejected_notes", []),
        )

    return CurationResult(decisions=decisions, selected_entries=selected_entries)
