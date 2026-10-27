# Bacon's Bento 🍱

An intentional digital garden and personal editorial taste engine. Curates reading and visual art reflecting deep craft, interdisciplinary collisions, and grounded optimism, dispatched to the `@baconbento` Telegram channel.

Read the [Bento Manifesto](MANIFESTO.md) for our core editorial principles, the 4 Pillars of Taste, and anti-goals.

---

## 🌿 Origins & Product Philosophy

Bacon's Bento began as a quiet personal sanctuary: a dedicated way for Pigar to document, digest, and honor an enduring fascination with longform writing, interdisciplinary collisions, and patient craftsmanship. In an internet culture optimized for speed, fragmented takes, and ephemeral feeds, Bento was created to slow down—to build a lasting, curated record of essays and archival discoveries that linger long after reading.

Throughout its creation, every product management and design decision was guided by an insistence on **calmness, minimalism, and contemplative restraint**:

* **Personal Garden Over Content Engine:** Bento is an open studio rather than an audience-growth project. There are no engagement loops, vanity metrics, or tracking tags. It is designed first and foremost to satisfy personal curiosity and editorial integrity.
* **Intentional Pull Over Automated Push:** While automated cron pipelines are the standard for web products, we deliberately retired scheduled cron runs. Curation is a mindful human ritual—initiated through the CLI (`bento new`) only when the curator sits down with the headspace to read, reflect, and assemble a plate.
* **Quiet, Contemplative Expression:** The language, summaries, and framing avoid hyperactive marketing cadence or breathless commentary. Dispatches speak in spare, grounded prose that invites reflection rather than urgency.
* **The Bento Plate Metaphor (Balance & Satiety):** Just as a traditional bento balances distinct textures and flavors into a finite, artful meal, each issue caps itself at five balanced courses. It respects the reader's cognitive attention, offering a moment of quiet focus rather than an infinite scroll.
* **The Chef's Pantry (Human Signal Over Algorithmic Firehoses):** Automated RSS feeds sweep the perimeter, but the highest-fidelity signal comes from what the curator personally reads and discovers. The Chef's Pantry bridges private research into public curation without polluting the publication stream.

---

## 🍱 The Ingestion Engines & Sources

Bacon's Bento combines automated perimeter sweeps with personal human capture:

### 1. The Perimeter Feeds (`config/registry.yaml`)
Curated RSS feeds spanning the foundational 4 reading courses and The Met API:
* **The Anchor (Philosophy & Meaning):** *Aeon, Psyche, Noema*
* **The Lens (Narrative Investigation):** *Coda Story, r/longform*
* **The Craft & Translation (Empirical & Mind):** *Knowable Magazine, Big Think*
* **The Cultural Garnish (Oddities & Visuals):** *The Public Domain Review*
* **The Visual Ambient Garnish:** *The Metropolitan Museum of Art Open Access Collection* (CC0 high-res art & antiquities)

### 2. The Chef's Pantry (Personal Reserve)
A pre-vetted reservoir of articles discovered during personal browsing, funneled through a zero-friction dual capture loop:
* **Desktop Research (Obsidian Vault):** Articles saved into `Clippings/*.md` with YAML frontmatter (`source`, `title`, `topic`, `description`) are read directly from local storage.
* **Mobile On-the-Go (Telegram Bot DM):** Web articles encountered while mobile are forwarded privately to `@MellowBreak_bot`. Forwarded links are automatically converted and saved as markdown clippings into your Obsidian vault (`Clippings/*.md`). You can also include course tags in your message (e.g. `#anchor`, `#lens`, `#craft`, `#garnish`).

> [!important] The 5-Course & Collision Guardrails
> The Chef's Pantry is a **candidate pool**, not an extra permanent slot. Articles compete for courses (`craft`, `lens`, `anchor`, `garnish`) based on their topic. Bento's **Source Collision Rule** strictly guarantees that at most **one** Chef's Pantry item can appear in any single issue, preventing personal bias from overwhelming the balanced tasting menu.

---

## 🍱 Editorial CLI

Bacon's Bento operates on an intentional, on-demand curation workflow. Rather than relying on an unprompted automated cron job, dispatches are initiated and curated directly through the terminal:

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python setup.py develop   # or pip install -e .
cp .env.example .env      # fill in tokens & chat IDs
```

### Curatorial Commands

You can run `bento` (if inside `.venv`) or `./bento` directly from the repository root:

```bash
./bento new              # Ingest feeds, draft issue, save note to Obsidian & preview in Telegram
./bento new --dry-run    # Preview candidate issue in terminal without saving or notifying
./bento preview          # Inspect current pending draft in terminal (syncs live Obsidian edits)
./bento update <URL>     # Replace/feature an article in the pending draft & re-synthesize intro
./bento publish          # Publish approved issue (with live Obsidian edits) to @baconbento
./bento status           # Inspect hopper metrics, unseen candidate count, and draft status
./bento bootstrap        # Record current feed entries as seen without drafting
```

### ✍️ File-Backed Obsidian Editing Workflow

Bento issues are treated as contemplative essays rather than fire-and-forget bot broadcasts. The review and editing workflow lives inside your Obsidian vault:

1. **Drafting (`./bento new`):**
   - Assembles candidates across perimeter RSS and Chef's Pantry.
   - Evaluates with the Decision Model and synthesizes with the Drafter Model.
   - Saves a formatted draft note directly to your vault:
     `Bento Output Volumes/Bacon Bento Vol {N} - {YYYY-MM-DD}.md`
   - Dispatches behind-the-scenes rationales and layout preview to your private Telegram admin chat.

2. **Featuring or Swapping Articles (`./bento update`):**
   - Want to feature an article directly or replace a course selection in the pending draft?
   - Run `./bento update <URL> [--course craft|anchor|lens|garnish]`.
   - Fetches the article metadata, mirrors a markdown clipping note into your vault (`Clippings/`), and triggers the Drafter Model to re-synthesize the **Thematic Synthesis Intro** and unified issue copy.

3. **Polishing in Obsidian:**
   - Open the note in Obsidian (`Bento Output Volumes/`).
   - The note contains YAML frontmatter (`issue_number`, `status: pending`, Met artwork metadata, and selected reading entries) followed by the essayistic copy.
   - Edit freely in your editor of choice using natural Markdown (`[links](...)`, `**bold**`, `*italics*`, `> quotes`) or native HTML (`<b>`, `<i>`, `<a href="...">`).

4. **Terminal Verification (`./bento preview`):**
   - Reads the latest draft note directly from `Bento Output Volumes/`.
   - Normalizes Markdown to Telegram-safe HTML and renders ANSI preview in the terminal.

5. **Broadcasting (`./bento publish`):**
   - Reads your finalized note from Obsidian.
   - Dispatches the formatted text and high-res Met artwork to `@baconbento`.
   - Automatically marks the Obsidian note frontmatter as `status: published` (`published_at: <timestamp>`).
   - Records seen entries and Met artwork in SQLite for deduplication.

Configure your vault folder via `BENTO_ISSUES_PATH` in `.env` (defaults to `~/Documents/Bacon Notes/1. Personal/Github Projects/bacons-bento/Bento Output Volumes`).

Edit [`config/registry.yaml`](config/registry.yaml) to inspect or modify source metadata, editorial rationales, and department filters. It is the single source of truth for sources.

Check source health (read-only, needs network):

```bash
python -m scripts.check_feeds
```

*Last audit (2026-10-14): 8/8 RSS feeds healthy. Daedalus, Ocula and Cabinet were removed (403 / Cloudflare / dormant).*

---

## GitHub Actions

1. Repository secrets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (`@baconbento`), and `OPENROUTER_API_KEY`.
2. Automatic cron schedules are retired in favor of intentional on-demand curation (`./bento new`).
3. Manual `workflow_dispatch` remains available in GitHub Actions as a cloud runner fallback. Deduplication state persists on the `state` branch.

