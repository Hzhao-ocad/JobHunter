This is a WIP art job hunting program with Discord integration.

It scrapes job listings from multiple sources, filters them through an LLM using
saved user interests, stores the results in SQLite, and announces matched jobs
in Discord.

Source now lives under `jobhunter/`:

- `jobhunter/scrapers/` manages scraper sources and the scraper registry.
- `jobhunter/pipeline/` runs scraping, filtering, scheduling, and status updates.
- `jobhunter/storage/` owns database access.
- `jobhunter/discord/` owns the Discord bot and message formatting.
- `jobhunter/ui/` contains the Streamlit dashboards.

Root-level files such as `Main.py`, `LLMLayer.py`, and `JobStruct.py` remain as
compatibility wrappers. New code should import from `jobhunter.*`.

See `docs/architecture.md` and `docs/scraper_contract.md` for the current
organization and scraper workflow.
