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

---

## 🍱 The Bento Plate

Bacon's Bento sources from a curated editorial registry (`config/registry.yaml`) spanning five balanced courses:


1. **The Anchor (Philosophy & Meaning):** *Aeon, Psyche, Noema*
2. **The Lens (Narrative Investigation):** *Coda Story, r/longform*
3. **The Craft & Translation (Empirical & Mind):** *Knowable Magazine, Big Think*
4. **The Cultural Garnish (Oddities & Visuals):** *The Public Domain Review*
5. **The Visual Ambient Garnish:** *The Metropolitan Museum of Art Open Access Collection* (CC0 high-res art & antiquities)

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
./bento new              # Ingest feeds, draft issue, preview in terminal & Telegram
./bento new --dry-run    # Preview candidate issue in terminal without saving or notifying
./bento preview          # Inspect current pending draft in terminal
./bento publish          # Confirm and broadcast approved issue to @baconbento
./bento status           # Inspect hopper metrics, unseen candidate count, and draft status
./bento bootstrap        # Record current feed entries as seen without drafting
```

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

