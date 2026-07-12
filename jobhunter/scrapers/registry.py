"""Central registry of available job scrapers."""

from __future__ import annotations

import json
from importlib import import_module

from jobhunter.paths import CONFIG_DIR
from jobhunter.scrapers.base import ScraperSpec


def _lazy_fetch(module_name: str, function_name: str = "scrape_jobs"):
    def _fetch():
        module = import_module(module_name)
        return getattr(module, function_name)()

    return _fetch


SCRAPERS = [
    ScraperSpec("uoft_cupe", "getUoftjobs", _lazy_fetch("jobhunter.scrapers.sources.uoft_cupe")),
    ScraperSpec("general_jobspy", "GetGeneralJobs", _lazy_fetch("jobhunter.scrapers.sources.general_jobspy")),
    ScraperSpec("akimbo", "GetAkimboJobs", _lazy_fetch("jobhunter.scrapers.sources.akimbo")),
    ScraperSpec("ocadu_taleo", "OCADU_Scrape", _lazy_fetch("jobhunter.scrapers.sources.ocadu_taleo")),
    ScraperSpec(
        "interactive_immersive",
        "GetInteractiveImmersiveJobs",
        _lazy_fetch("jobhunter.scrapers.sources.interactive_immersive"),
    ),
]


def enabled_scrapers() -> list[ScraperSpec]:
    enabled_by_id = _load_enabled_overrides()
    return [
        scraper
        for scraper in SCRAPERS
        if enabled_by_id.get(scraper.id, scraper.enabled)
    ]


def _load_enabled_overrides() -> dict[str, bool]:
    config_path = CONFIG_DIR / "scrapers.json"
    if not config_path.exists():
        return {}

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    overrides: dict[str, bool] = {}
    for item in raw.get("scrapers", []):
        if not isinstance(item, dict):
            continue
        scraper_id = str(item.get("id") or "").strip()
        if not scraper_id:
            continue
        overrides[scraper_id] = bool(item.get("enabled", True))
    return overrides
