"""Run configured scrapers and collect source-tagged results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from jobhunter.scrapers.base import ScraperSpec
from jobhunter.scrapers.registry import enabled_scrapers


@dataclass(frozen=True)
class ScraperResult:
    scraper: ScraperSpec
    jobs: List[Dict[str, object]]


def run_enabled_scrapers(scrapers: list[ScraperSpec] | None = None) -> list[ScraperResult]:
    results: list[ScraperResult] = []
    for scraper in scrapers or enabled_scrapers():
        jobs = scraper.fetch()
        results.append(ScraperResult(scraper=scraper, jobs=jobs))
    return results
