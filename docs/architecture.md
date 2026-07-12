# JobHunter Architecture

The source code is now organized as a package under `jobhunter/`.

```text
jobhunter/config/          config parsing and profile needs
jobhunter/pipeline/        scheduler, pipeline runner, status store
jobhunter/jobs/            normalized job construction and formatting
jobhunter/storage/         database connection, schema, repositories
jobhunter/llm/             LLM client and response parsing
jobhunter/scrapers/        scraper registry, runner, and source modules
jobhunter/discord/         Discord bot, state, and embed formatting
jobhunter/ui/              Streamlit dashboards
jobhunter/observability/   diagnostic JSONL logger
```

Root-level files such as `Main.py`, `LLMLayer.py`, and `JobStruct.py` are
compatibility wrappers. New code should import from `jobhunter.*`.

Runtime data still uses the existing root folders:

```text
database/
logs/
```

Those paths are centralized in `jobhunter/paths.py`.

