# Bacon's Bento 🍱

An intentional digital garden and personal editorial taste engine. Curates reading and visual art reflecting deep craft, interdisciplinary collisions, and grounded optimism, dispatched to the `@baconbento` Telegram channel.

Read the [Bento Manifesto](MANIFESTO.md) for our core editorial principles, the 4 Pillars of Taste, and anti-goals.

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

