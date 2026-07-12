# JobHunter Scraper Contract

Scrapers live under `jobhunter/scrapers/sources/` and are managed through the
central registry in `jobhunter/scrapers/registry.py`.

The pipeline no longer imports individual scrapers directly. It asks the
registry for enabled scraper specs, runs them in order, logs each result set,
and combines the returned job dictionaries.

## Required Entrypoint

Every scraper module should expose:

```python
def scrape_jobs() -> list[dict]:
    ...
```

Existing compatibility names such as `GetAkimboJobs()` or `OCADU_Scrape()` may
remain, but `scrape_jobs()` is the standard package entrypoint.

## Required Job Format

Each scraper must return a `list[dict]`. The safest way to produce a valid
record is to use:

```python
from jobhunter.jobs.model import build_job_data


def scrape_jobs() -> list[dict]:
    return [
        build_job_data(
            job_title="Gallery Assistant",
            company_name="Example Arts Centre",
            job_location="Toronto, ON",
            job_description="Assist with exhibition installation and visitor support.",
            job_url="https://example.org/jobs/gallery-assistant",
            date="2026-06-29",
            job_type="part-time",
            is_remote=False,
            salary="$22/hour",
            source="Example Arts Centre",
            raw_columns=["department: Exhibitions", "deadline: 2026-07-15"],
        )
    ]
```

## Canonical Fields

`build_job_data(...)` returns the shape expected by the LLM filter, database,
dashboard, and Discord bot:

```text
job_title
job_location
job_description
job_url
date
type
isRemote
salary
company_name
source
LLMComment
raw_columns
```

Important rules:

- `is_remote` must be a real boolean, not `"N/A"` or `"False"`.
- Prefer absolute `http` or `https` URLs.
- Preserve source-specific metadata in `raw_columns`.
- Use plain text descriptions, not raw page HTML.
- Keep `job_title`, `company_name`, and `job_location` specific because they
  are used for deduplication.

## Adding A Scraper

1. Add a file under `jobhunter/scrapers/sources/`, for example
   `example_source.py`.
2. Implement `scrape_jobs() -> list[dict]`.
3. Build every job with `jobhunter.jobs.model.build_job_data`.
4. Add a `ScraperSpec` to `SCRAPERS` in `jobhunter/scrapers/registry.py`.
5. Add an entry to `config/scrapers.json` so it can be enabled or disabled.

Example registry entry:

```python
ScraperSpec(
    "example_source",
    "Example Source",
    _lazy_fetch("jobhunter.scrapers.sources.example_source"),
)
```

Example config entry:

```json
{"id": "example_source", "enabled": true}
```

## Current Scrapers

```text
uoft_cupe              -> jobhunter/scrapers/sources/uoft_cupe.py
general_jobspy         -> jobhunter/scrapers/sources/general_jobspy.py
akimbo                 -> jobhunter/scrapers/sources/akimbo.py
ocadu_taleo            -> jobhunter/scrapers/sources/ocadu_taleo.py
interactive_immersive  -> jobhunter/scrapers/sources/interactive_immersive.py
```

## Compatibility

Old imports under `JobScrapper/` still exist as wrappers, but new work should
use `jobhunter.scrapers.sources`.

