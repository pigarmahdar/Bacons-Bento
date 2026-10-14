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

## Local Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in token + chat id
python -m pytest
python -m src.main --dry-run      # preview posts without sending
python -m src.main --bootstrap    # record current entries, post nothing
python -m src.main                # live run (max 5 posts)
```

Edit [`config/registry.yaml`](config/registry.yaml) to inspect or modify source metadata, editorial rationales, and department filters. It is the single source of truth for sources.

Check source health (read-only, needs network):

```bash
python -m scripts.check_feeds
```

*Last audit (2026-10-14): 8/8 RSS feeds healthy. Daedalus, Ocula and Cabinet were removed (403 / Cloudflare / dormant).*

---

## GitHub Actions

1. Add repository secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (`@baconbento`).
2. Run the **Bento** workflow manually with `bootstrap = true` once.
3. The workflow runs daily; deduplication state persists on the `state` branch.
