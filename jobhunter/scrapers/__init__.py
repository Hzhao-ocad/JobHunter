from jobhunter.scrapers.base import ScraperSpec
from jobhunter.scrapers.registry import SCRAPERS, enabled_scrapers
from jobhunter.scrapers.runner import ScraperResult, run_enabled_scrapers

__all__ = [
    "SCRAPERS",
    "ScraperResult",
    "ScraperSpec",
    "enabled_scrapers",
    "run_enabled_scrapers",
]
