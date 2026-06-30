# JobStruct Scraper Contract

This document is for future LLM agents or developers adding new job scrapers to
JobHunter. A scraper is compatible with the current pipeline when it returns a
list of normalized job dictionaries matching the structure produced by
`JobStruct.build_job_data`.

## Where JobStruct Fits

The pipeline in `LLMLayer.FindMeSomeJobs` does this:

1. Calls scraper entrypoints such as `getUoftjobs()`, `GetGeneralJobs()`,
   `GetAkimboJobs()`, and `OCADU_Scrape()`.
2. Combines all returned jobs into one list.
3. Deduplicates jobs by `JobStruct.compute_dedupe_key(job)`.
4. Filters out jobs that already have a status row for each user's profile.
5. Converts each job to LLM-readable text with `JobStruct.parse_job_data(job)`.
6. Stores LLM-relevant jobs as `new` profile jobs and non-recommended jobs as
   `unwanted` profile jobs with `JobStruct.add_job_to_db(...)`.

Scrapers should return data that is already normalized enough for steps 3-6 to
work without special handling.

## Required Scraper Return Format

Each scraper entrypoint should return:

```python
list[dict]
```

Each dictionary should use the JobStruct keys below. The safest way to produce a
valid dictionary is to call `build_job_data(...)` instead of hand-building the
dict.

```python
from JobStruct import build_job_data

def GetExampleJobs():
    jobs = []
    jobs.append(
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
            raw_columns=[
                "department: Exhibitions",
                "deadline: 2026-07-15",
            ],
        )
    )
    return jobs
```

## Canonical Job Fields

`build_job_data` returns a dictionary with these keys:

| Key | Type | Meaning | Notes |
| --- | --- | --- | --- |
| `job_title` | `str` | Job/listing title. | Important for dedupe. Avoid generic titles when possible. |
| `job_location` | `str` | Human-readable location. | Important for dedupe. Include city/province/state when available. |
| `job_description` | `str` | Plain text description. | Used heavily by the LLM. Prefer useful text over raw HTML. |
| `job_url` | `str` | Canonical listing URL. | Strongest duplicate check. Use an absolute `http`/`https` URL when possible. |
| `date` | `str` | Posted date, deadline, or source date. | Stored as text. ISO dates are preferred when known. |
| `type` | `str` | Normalized job type. | Set through the `job_type` argument. See type normalization below. |
| `isRemote` | `bool` | Whether the role is remote/hybrid/work-from-home. | Must be a real boolean. Do not pass `"N/A"` or other strings. |
| `salary` | `str` | Salary/pay text. | Empty string is fine when unknown. |
| `company_name` | `str` | Employer, institution, organizer, or source organization. | Important for dedupe. |
| `source` | `str` | Name of scraper/source site. | Examples: `Akimbo`, `OCADU Taleo`, `jobspy`. |
| `LLMComment` | `str` | LLM recommendation reason. | Scrapers should usually leave this at the default. |
| `raw_columns` | `list[str]` | Source-specific metadata. | Stored as JSON text in SQLite and included in LLM text. |

Extra keys are tolerated in memory, but they are not inserted into the database.
For example, `Akimbo.py` adds an `index` key, but `add_job_to_db` ignores it.

## `build_job_data` Arguments

Use these keyword arguments:

```python
build_job_data(
    job_title="",
    job_location="",
    job_description="",
    job_url="",
    date="",
    job_type="",
    is_remote=False,
    salary="",
    company_name="",
    source="UofT CUPE 3902",
    llm_comment="LLM didn't provide any comment",
    raw_columns=None,
)
```

Important behavior:

- `job_type` is normalized into `type`.
- `is_remote` is copied into `isRemote` without strict coercion, so pass only
  `True` or `False`.
- `raw_columns=None` becomes an empty list.
- `llm_comment=""` becomes the default comment.

## Job Type Normalization

`JobStruct._normalize_job_type` only recognizes these patterns:

| Input contains | Stored `type` |
| --- | --- |
| `intern` | `intern` |
| `part` | `part` |
| `full` | `full` |
| anything else | empty string |

Examples:

- `job_type="Full-time"` stores `type="full"`.
- `job_type="Part Time"` stores `type="part"`.
- `job_type="Internship"` stores `type="intern"`.
- `job_type="Contract"` stores `type=""`.
- `job_type="N/A"` stores `type=""`.

If a site has richer values such as contract, temporary, volunteer, fellowship,
or seasonal, put that original value in `raw_columns` and optionally mention it
in `job_description`.

## Remote and Salary Inference

`parse_job_data(job)` formats a job for the LLM. While formatting, it may infer:

- salary from `job_description` or `raw_columns` if `salary` is empty;
- job type from title/description/raw columns if `type` is empty;
- remote status from `job_location`, `job_description`, or `raw_columns`.

The remote formatter uses `bool(job.get("isRemote"))`, so strings like `"N/A"`,
`"False"`, or `"no"` are truthy and will be treated as remote. Always pass a
real boolean.

## Database Compatibility

All JobHunter data now lives in one shared SQLite database:

```text
database/jobhunter.db
```

The `jobs` table stores canonical scraped jobs once:

```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
job_title TEXT,
job_location TEXT,
job_description TEXT,
job_url TEXT,
date TEXT,
type TEXT,
isRemote INTEGER,
salary TEXT,
company_name TEXT,
source TEXT,
raw_columns TEXT,
created_at TEXT NOT NULL,
updated_at TEXT NOT NULL,
dedupe_key TEXT NOT NULL
```

The `profiles` table stores one row per person/profile:

```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
name TEXT NOT NULL UNIQUE,
discord_user_id TEXT,
need TEXT,
created_at TEXT NOT NULL,
updated_at TEXT NOT NULL
```

The `profile_jobs` table stores the per-person job state:

```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
profile_id INTEGER NOT NULL,
job_id INTEGER NOT NULL,
status TEXT NOT NULL,
LLMComment TEXT,
created_at TEXT NOT NULL,
updated_at TEXT NOT NULL,
pushed_at TEXT
```

Notes:

- `isRemote` is stored as `1` or `0`.
- `raw_columns` is stored with `json.dumps(..., ensure_ascii=False)`.
- `jobs.created_at` is generated when a canonical job is first stored.
- `profile_jobs.created_at` is generated when a profile first receives that job.
- `dedupe_key` is generated from normalized title, company, and location.
- `profile_jobs.status` is one of:
  - `new`: relevant to the user but not yet pushed by the Discord bot.
  - `recommended`: already pushed to the user by the Discord bot.
  - `unwanted`: not relevant to that user.
- `LLMComment` is stored on `profile_jobs`, because each person can receive a
  different recommendation reason for the same canonical job.
- Legacy `database/{name}jobs.db` rows are imported as `recommended` and
  `database/{name}unwanted_jobs.db` rows are imported as `unwanted` the first
  time the shared DB schema is initialized.

## Duplicate Detection

There are three duplicate checks:

1. If `job_url` is non-empty, `job_exists` checks for that exact URL.
2. It then checks `dedupe_key`, computed from:
   - lowercased/trimmed `job_title`
   - lowercased/trimmed `company_name`
   - lowercased/trimmed `job_location`
3. As a fallback, it checks exact title/company/location text.

The database also has unique indexes on:

- `(job_url, job_title, company_name, job_location)`
- `dedupe_key`

Scraper guidance:

- Prefer stable canonical URLs over tracking URLs.
- Do not leave `company_name` or `job_location` blank if the site provides them.
- Avoid using placeholders like `"Akimbo Listing"` or `"N/A"` as URLs when a
  real URL exists.
- If multiple distinct listings have the same title, company, and location, add
  distinguishing text to the title or location, or improve the URL. Otherwise
  they may collapse under the dedupe key.

## LLM-Readable Format

`parse_job_data(job)` emits text like:

```text
Job Title: Gallery Assistant
Company Name: Example Arts Centre
Location: Toronto, ON
Date Posted: 2026-06-29
Job Type: part
Remote: no
Salary: $22/hour
Job URL: https://example.org/jobs/gallery-assistant
Source: Example Arts Centre
Job Description: Assist with exhibition installation and visitor support.
Raw Columns: department: Exhibitions
deadline: 2026-07-15
```

This is the text that the recommendation LLM sees. Scrapers should prioritize
clear title, company, location, description, salary, URL, and useful raw columns.

## Adding a New Scraper

1. Create a module under `JobScrapper/` or another appropriate project file.
2. Implement an entrypoint function that returns `list[dict]`.
3. Use `build_job_data(...)` for every returned job.
4. Normalize URLs with `urllib.parse.urljoin` when scraping relative links.
5. Convert HTML descriptions to readable plain text with BeautifulSoup
   `get_text(" ", strip=True)` or equivalent.
6. Preserve source-specific details in `raw_columns`.
7. Import and call the new scraper from `LLMLayer.FindMeSomeJobs`.
8. Add its results to the combined `alljobs` list and diagnostic logging.

Minimal integration pattern:

```python
from JobScrapper.Example import GetExampleJobs

ExampleJobs = GetExampleJobs()
_diag_logger.log_job_search_results("GetExampleJobs", ExampleJobs)
alljobs = Uoftjobs + GeneralJobs + AkimboJobs + OCADUJobs + ExampleJobs
```

## Compatibility Checklist

Before considering a scraper done:

- It returns `list[dict]`, not a pandas DataFrame, tuple list, or nested table.
- Every returned dict has the JobStruct keys because it came from
  `build_job_data`.
- `is_remote` is a boolean.
- `raw_columns` is a list of strings or can be JSON serialized.
- URLs are absolute where possible.
- `job_title`, `company_name`, and `job_location` are specific enough for
  dedupe.
- Descriptions are plain text, not unprocessed full-page HTML.
- The scraper handles an empty result set by returning `[]`.
- Network failures either raise a clear exception or are handled consistently
  with the style of existing scrapers.
