"""Common scraper metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List


ScrapedJob = Dict[str, object]
ScraperCallable = Callable[[], List[ScrapedJob]]


@dataclass(frozen=True)
class ScraperSpec:
    id: str
    name: str
    fetch: ScraperCallable
    enabled: bool = True

