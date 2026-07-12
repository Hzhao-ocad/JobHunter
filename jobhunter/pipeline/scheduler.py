"""Scheduling helpers for repeated pipeline runs."""

from __future__ import annotations

from datetime import datetime, time as day_time, timedelta
from typing import List


def parse_run_times(raw_times: str) -> List[day_time]:
    times: List[day_time] = []
    for token in raw_times.split(","):
        value = token.strip()
        if not value:
            continue
        try:
            parsed = datetime.strptime(value, "%H:%M").time()
        except ValueError as exc:
            raise ValueError(
                f"Invalid time '{value}'. Use 24-hour HH:MM format, e.g. 03:00,14:00."
            ) from exc
        times.append(parsed)

    if not times:
        raise ValueError("No valid run times provided.")

    unique = {(t.hour, t.minute): t for t in times}
    return sorted(unique.values(), key=lambda t: (t.hour, t.minute))


def get_next_run(now: datetime, run_times: List[day_time]) -> datetime:
    candidates: List[datetime] = []
    for run_time in run_times:
        candidate = now.replace(
            hour=run_time.hour,
            minute=run_time.minute,
            second=0,
            microsecond=0,
        )
        if candidate <= now:
            candidate += timedelta(days=1)
        candidates.append(candidate)
    return min(candidates)

