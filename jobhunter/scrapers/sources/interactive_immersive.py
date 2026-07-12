#!/usr/bin/env python3
"""Standalone scraper for Interactive & Immersive Jobs.

The public archive pages are protected by a browser challenge, but the site's
WordPress REST API exposes the same ``job_listing`` posts with full rendered
content and WP Job Manager metadata.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from jobhunter.jobs.model import build_job_data
import sys


SOURCE_NAME = "Interactive & Immersive Jobs"
BASE_URL = "https://jobs.interactiveimmersive.io/"
REST_BASE_URL = urljoin(BASE_URL, "wp-json/wp/v2/")
JOB_LISTINGS_ENDPOINT = urljoin(REST_BASE_URL, "job-listings")
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return html.unescape(str(value)).replace("\xa0", " ").strip()


def _html_to_text(rendered_html: str) -> str:
    if not rendered_html:
        return ""

    soup = BeautifulSoup(rendered_html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text("\n", strip=True)
    lines = [re.sub(r"\s+", " ", _clean_text(line)) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _rendered_text(field: Any) -> str:
    if isinstance(field, dict):
        return _clean_text(field.get("rendered", ""))
    return _clean_text(field)


def _rendered_html(field: Any) -> str:
    if isinstance(field, dict):
        return str(field.get("rendered", "") or "")
    return str(field or "")


def _parse_post_date(date_value: str) -> str:
    return _clean_text(date_value)[:10]


def _is_remote(meta: Dict[str, Any], location: str, description: str) -> bool:
    remote_value = meta.get("_remote_position")
    if remote_value in (True, 1, "1", "true", "True", "yes", "Yes"):
        return True

    combined = f"{location} {description}".lower()
    return any(keyword in combined for keyword in ("remote", "hybrid", "work from home"))


def _extract_salary(text: str) -> str:
    if not text:
        return ""

    pattern = re.compile(
        r"(\$\s?[\d,]+(?:\.\d+)?(?:\s?(?:-|to)\s?\$?\s?[\d,]+(?:\.\d+)?)?"
        r"(?:\s?(?:/|per)\s?(?:hour|hr|year|yr|annum))?)",
        flags=re.IGNORECASE,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _format_salary(meta: Dict[str, Any], description: str) -> str:
    salary = _clean_text(meta.get("_job_salary"))
    currency = _clean_text(meta.get("_job_salary_currency"))
    unit = _clean_text(meta.get("_job_salary_unit"))

    if salary:
        parts = []
        if currency:
            parts.append(currency)
        parts.append(salary)
        if unit:
            parts.append(f"per {unit}")
        return " ".join(parts)

    return _extract_salary(description)


def _guess_job_type(title: str, description: str) -> str:
    combined = f"{title} {description}".lower()
    if re.search(r"\bintern(ship)?\b", combined):
        return "intern"
    if re.search(r"\bpart[-\s]?time\b", combined):
        return "part"
    if re.search(r"\bfull[-\s]?time\b", combined):
        return "full"
    return ""


def _chunked(values: Iterable[int], size: int = 100) -> Iterable[List[int]]:
    chunk: List[int] = []
    for value in values:
        chunk.append(value)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _request_json(
    session: requests.Session,
    url: str,
    *,
    timeout: int,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    response = session.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _fetch_listing_page(
    session: requests.Session,
    page: int,
    *,
    per_page: int,
    timeout: int,
) -> List[Dict[str, Any]]:
    params = {"per_page": per_page, "page": page}
    data = _request_json(session, JOB_LISTINGS_ENDPOINT, params=params, timeout=timeout)
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected REST response for page {page}: expected a list")
    return data


def _fetch_listing_detail(
    session: requests.Session,
    item: Dict[str, Any],
    *,
    timeout: int,
) -> Dict[str, Any]:
    self_links = item.get("_links", {}).get("self", [])
    detail_url = ""
    if self_links and isinstance(self_links, list):
        detail_url = self_links[0].get("href", "")

    if not detail_url:
        item_id = item.get("id")
        if item_id:
            detail_url = urljoin(JOB_LISTINGS_ENDPOINT + "/", str(item_id))

    if not detail_url:
        return item

    try:
        data = _request_json(session, detail_url, timeout=timeout)
    except requests.RequestException:
        return item

    return data if isinstance(data, dict) else item


def _fetch_term_map(
    session: requests.Session,
    endpoint: str,
    term_ids: Iterable[int],
    *,
    timeout: int,
) -> Dict[int, str]:
    ids = sorted({int(term_id) for term_id in term_ids if str(term_id).isdigit()})
    if not ids:
        return {}

    term_map: Dict[int, str] = {}
    for chunk in _chunked(ids):
        params = {"include": ",".join(str(term_id) for term_id in chunk), "per_page": len(chunk)}
        try:
            data = _request_json(
                session,
                urljoin(REST_BASE_URL, endpoint),
                params=params,
                timeout=timeout,
            )
        except requests.RequestException:
            continue

        if not isinstance(data, list):
            continue

        for term in data:
            try:
                term_id = int(term.get("id"))
            except (TypeError, ValueError):
                continue
            term_map[term_id] = _clean_text(term.get("name"))

    return term_map


def _term_names(item: Dict[str, Any], field: str, term_map: Dict[int, str]) -> List[str]:
    names: List[str] = []
    for term_id in item.get(field, []) or []:
        try:
            name = term_map.get(int(term_id), "")
        except (TypeError, ValueError):
            name = ""
        if name:
            names.append(name)
    return names


def _build_raw_columns(
    item: Dict[str, Any],
    meta: Dict[str, Any],
    categories: List[str],
    experience: List[str],
    page: int,
) -> List[str]:
    raw_columns = [
        f"source_post_id: {item.get('id', '')}",
        f"archive_page: {page}",
        f"application_url: {_clean_text(meta.get('_application')) or 'N/A'}",
        f"company_website: {_clean_text(meta.get('_company_website')) or 'N/A'}",
        f"featured: {_clean_text(meta.get('_featured')) or '0'}",
        f"filled: {_clean_text(meta.get('_filled')) or '0'}",
    ]

    if categories:
        raw_columns.append(f"categories: {', '.join(categories)}")
    if experience:
        raw_columns.append(f"experience: {', '.join(experience)}")

    return raw_columns


def _item_to_job(
    item: Dict[str, Any],
    *,
    page: int,
    category_map: Dict[int, str],
    experience_map: Dict[int, str],
) -> Dict[str, Any]:
    meta = item.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}

    title = _rendered_text(item.get("title"))
    description = _html_to_text(_rendered_html(item.get("content")))
    location = _clean_text(meta.get("_job_location"))
    company_name = _clean_text(meta.get("_company_name"))
    job_url = _clean_text(item.get("link"))
    categories = _term_names(item, "job-categories", category_map)
    experience = _term_names(item, "job_listing_experience", experience_map)

    return build_job_data(
        job_title=title,
        company_name=company_name,
        job_location=location,
        job_description=description,
        job_url=job_url,
        date=_parse_post_date(item.get("date", "")),
        job_type=_guess_job_type(title, description),
        is_remote=_is_remote(meta, location, description),
        salary=_format_salary(meta, description),
        source=SOURCE_NAME,
        raw_columns=_build_raw_columns(item, meta, categories, experience, page),
    )


def scrape_interactive_immersive_jobs(
    start_page: int = 1,
    end_page: int = 5,
    *,
    per_page: int = 10,
    timeout: int = 20,
    fetch_details: bool = True,
) -> List[Dict[str, Any]]:
    """Scrape Interactive & Immersive job listings into JobStruct dictionaries."""
    if start_page < 1:
        raise ValueError("start_page must be 1 or greater")
    if end_page < start_page:
        raise ValueError("end_page must be greater than or equal to start_page")

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    items_with_pages: List[tuple[Dict[str, Any], int]] = []
    for page in range(start_page, end_page + 1):
        page_items = _fetch_listing_page(session, page, per_page=per_page, timeout=timeout)
        for item in page_items:
            if fetch_details:
                item = _fetch_listing_detail(session, item, timeout=timeout)
            items_with_pages.append((item, page))

    category_ids = []
    experience_ids = []
    for item, _page in items_with_pages:
        category_ids.extend(item.get("job-categories", []) or [])
        experience_ids.extend(item.get("job_listing_experience", []) or [])

    category_map = _fetch_term_map(session, "job-categories", category_ids, timeout=timeout)
    experience_map = _fetch_term_map(
        session,
        "job_listing_experience",
        experience_ids,
        timeout=timeout,
    )

    return [
        _item_to_job(item, page=page, category_map=category_map, experience_map=experience_map)
        for item, page in items_with_pages
    ]


def GetInteractiveImmersiveJobs() -> List[Dict[str, Any]]:
    """Convenience entrypoint matching the style of the existing scrapers."""
    return scrape_interactive_immersive_jobs()


def scrape_jobs() -> List[Dict[str, Any]]:
    return GetInteractiveImmersiveJobs()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.WARNING)

    parser = argparse.ArgumentParser(description="Scrape Interactive & Immersive Jobs.")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int, default=5)
    parser.add_argument("--per-page", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument(
        "--no-detail-fetch",
        action="store_true",
        help="Use archive REST records only instead of fetching each listing's REST detail endpoint.",
    )
    args = parser.parse_args()

    jobs = scrape_interactive_immersive_jobs(
        start_page=args.start_page,
        end_page=args.end_page,
        per_page=args.per_page,
        timeout=args.timeout,
        fetch_details=not args.no_detail_fetch,
    )
    print(json.dumps(jobs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
