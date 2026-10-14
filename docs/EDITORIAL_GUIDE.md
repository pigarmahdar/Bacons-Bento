# Bacon's Bento: Editorial Specification & Formatting Guide 🍱

This document formalizes the voice, prompt guidelines, and structural requirements for every weekly issue of **Bacon's Bento** (`@baconbento`). Any changes to AI models, cron jobs, or pipeline logic must adhere to these standards to maintain strict editorial consistency.

---

## 1. The Weekly Plate Architecture

Every weekly issue represents a single cohesive "Bento Plate" of up to 5 courses:

1. **⚓ The Anchor (Philosophy & Meaning):** Deep reflections on ethics, interiority, and existential frameworks (*Aeon, Psyche, Noema*).
2. **👁 The Lens (Narrative Investigation):** Rigorous, thematic, non-cyclical reporting on systemic dynamics (*Coda Story, r/longform*).
3. **🩺 The Craft & Translation (Concepts & Science):** Empirical science and mental models translated with clarity (*Knowable Magazine, Big Think*).
4. **🃏 The Cultural Garnish (Curiosities & Oddities):** Idiosyncratic essays, archival oddities, and subcultural moments (*The Public Domain Review, Them Culture*).
5. **🌳 The Visual Ambient Garnish (The Met Collection):** High-resolution, CC0 public-domain art, antiquities, and prints from The Metropolitan Museum of Art Open Access Collection.

> **The "Silence Beats Noise" Rule:** If no candidate in a course meets the standards of the 4 Pillars of Taste, that course slot is left empty for the week. We never fill a course with mediocre padding.

---

## 2. Approved Telegram Output Format

The output must be formatted using clean Telegram HTML (`<b>`, `<i>`, `<a href="...">`) and stay under 2,400 characters.

```html
🍱 <b>Bacon's Bento · Issue #N</b>

[Thematic Synthesis Intro: 2–4 sentences weaving together the subtle nuances, common threads, and tensions connecting the selected pieces. Avoid meta-commentary like "This week we explore"; articulate the conceptual undercurrent that links them together.]

⚓ <b>The Anchor</b>
<i>[Linked Article Title]</i> — <a href="[URL]">[Source Name]</a>
[1–2 sentences of thoughtful commentary/hook reflecting Bento's aesthetic: patience, interiority, defamiliarization.]

👁 <b>The Lens</b>
<i>[Linked Article Title]</i> — <a href="[URL]">[Source Name]</a>
[1–2 sentences: tension, systemic depth, non-obvious dynamics.]

🩺 <b>The Craft</b>
<i>[Linked Article Title]</i> — <a href="[URL]">[Source Name]</a>
[1–2 sentences: lucid translation of complex ideas, tension between craft and limits.]

🃏 <b>The Garnish</b>
<i>[Linked Article Title]</i> — <a href="[URL]">[Source Name]</a>
[1–2 sentences: oddities, archival wonder, forgotten human craft.]

🌳 <b>Visual Garnish</b>
<i><a href="[Met URL]">[Artwork Name] ([Year])</a></i>
<i>[Artist] · [Medium] · [Department], The Met Collection (CC0)</i>
[1 sentence: quiet atmospheric observation linking light, craft, or form.]

— <i>slow ideas, quiet craft, curious intersections.</i>
```

---

## 3. Two-Stage LLM Workflow

### Stage 1: The Decision Model (`typesafe/jev-1.13`)
- **Inputs:** Pool of unseen candidate articles from enabled feeds + `MANIFESTO.md` principles.
- **Engine:** TypeSafe Jev Decision API via OpenRouter (`/api/alpha/decisions`).
- **Constraints:**
  - Strictly reject items violating Anti-Pillars (24-hour cycle rage, party politics, hot takes, listicles, paywalled clickbait).
  - Select at most 1 item per course, and at most 1 item from any single source.
  - Return selection in structured JSON with editorial rationales explaining which pillar was satisfied.

### Stage 2: The Drafter Model (`xiaomi/mimo-v2.6-flash`)
- **Inputs:** The chosen articles + chosen Met CC0 artwork.
- **Output:** Formatted HTML adhering strictly to the template above, producing the signature Thematic Synthesis Intro and course blurbs.

---

## 4. Review & Approval Protocol

1. **Draft Generation (`python -m src.main --draft`):**
   - The cron runs weekly (e.g. Thursday evening).
   - Generates the candidate selections and formatted issue.
   - Saves draft in SQLite (`drafts` table).
   - Dispatches a private preview message to `TELEGRAM_ADMIN_CHAT_ID` detailing:
     - The Decision Model's rationales for each course.
     - The exact Telegram HTML preview.
     - The Issue ID.
2. **Review & Approval (`python -m src.main --approve <ID>`):**
   - The curator reviews the draft on Telegram.
   - If approved, it is dispatched to `@baconbento` and marked as posted.
