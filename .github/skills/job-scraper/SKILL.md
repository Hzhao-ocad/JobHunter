---
name: job-scraper
description: 'Scrape job listings from websites into normalized job records. Use for planning or implementing job scrapers, choosing extraction strategy, collecting required fields, deduplicating results, and validating data quality before DB insertion.'
argument-hint: 'Describe the target site, search terms, location filters, and preferred output (DB or CSV).'
user-invocable: true
---

# Job Scraper

## What This Skill Produces
- A repeatable scraper workflow for one or more job sites.
- Normalized job dictionaries that fit this project schema.
- Quality checks that catch missing fields, duplicates, and broken selectors early.

## When To Use
- Add a new job source site.
- Fix a scraper after website HTML changes.
- Improve extraction quality for title, location, URL, date, salary, and remote fields.
- Prepare scraped records for DB insertion and LLM filtering.

## Target Output Schema
Use normalized records with these keys:
- job_title
- job_location
- job_description
- job_url
- date
- type
- isRemote
- salary
- company_name
- source
- LLMComment
- raw_columns

## Formal Function Requirement
- Every scraper module must expose a public function named `Filename_Scrape()`.
- `Filename` is a placeholder for the current file name stem (without `.py`), not the literal word `Filename`.
- Example: `OCADU.py` must define `OCADU_Scrape()`.
- `Filename_Scrape()` must return normalized job listings that follow the Target Output Schema in this skill.
- The returned value should be a list of normalized job dictionaries, ready for dedupe and persistence checks.

## Step-by-Step Workflow
1. Define scrape scope and constraints.
   - Confirm target website(s), search terms, location, and freshness window.
   - Confirm legal and ethical boundaries (robots.txt, terms of service, rate limits).
   - Define required fields and fallback defaults for missing values.

2. Inspect source structure before coding.
   - Identify whether data is static HTML, paginated HTML, or API-backed dynamic content.
   - Capture stable selectors for listing container, title, link, date, location, and company.
   - Note pagination or filter query parameters.

3. Choose extraction strategy.
   - Use requests + BeautifulSoup for static HTML.
   - Use API calls if the site exposes clean JSON.
   - Use a library source adapter if available (for example, jobspy for broad aggregators).

4. Implement source-specific extractor.
   - Fetch with timeout, headers, and basic retry handling.
   - Parse listings and extract all possible fields.
   - Build absolute URLs from relative links.
   - Keep a raw snapshot (raw_columns) for traceability and later parser fixes.

5. Normalize to project schema.
   - Convert each listing to a normalized dict using a helper like build_job_data.
   - Standardize job type and remote detection.
   - Normalize date format to a stable string.
   - Fill missing optional fields with empty string or N/A, never None for final persisted values.

6. Quality checks before persistence.
   - Drop rows with no job_title and no job_url.
   - Validate URL format and remove obvious junk links.
   - Deduplicate by canonical job_url first; fallback key is title + company + location.
   - Report extraction coverage (percent of rows with non-empty key fields).

7. Store and route data.
   - Insert only new records by checking existing jobs DB and unwanted jobs DB.
   - Keep source tags so downstream filtering can compare source quality.
   - Pass normalized records to LLM ranking only after schema checks pass.

8. Add regression guard.
   - Add a smoke test or fixture for the parser when possible.
   - Keep selector assumptions documented in comments near parser logic.
   - Re-run after website changes and compare coverage metrics.

## Decision Points And Branching
- If selectors are unstable or deeply nested:
  - Prefer structural anchors (table id, card wrapper class, semantic tags) over brittle nth-child selectors.
- If the website is JS-rendered:
  - Look for internal JSON endpoints first.
  - Only use browser automation when API/static parse is not possible.
- If duplicate volume is high:
  - Tighten canonical URL logic and normalize trailing slashes/query noise.
- If many fields are blank:
  - Expand selector fallbacks and pull text from nearby metadata blocks.

## Completion Criteria
A scraper task is complete when all checks pass:
- Returns a list of normalized dict records with required keys.
- 95%+ rows contain non-empty job_title or job_url.
- 90%+ rows contain source and date (or explicit N/A where date is unavailable).
- Duplicate rate after dedupe is acceptably low for the source.
- No unhandled exceptions on empty or changed page structures.

## Quick Checklist Mode
Use this when the user asks for a fast run:
- Confirm target URL and fields.
- Fetch with timeout and headers.
- Parse with stable selectors and URL joining.
- Normalize with build_job_data.
- Dedupe and drop unusable rows.
- Validate coverage metrics.
- Save to DB/CSV and report counts.

## Example Prompts
- Add a scraper for this job board URL and normalize output to the JobHunter schema.
- Debug why this scraper now returns zero rows and harden selectors.
- Build a parser that extracts title, company, location, date, link, and salary with fallbacks.
- Add dedupe and coverage reporting to this existing scraper function.
