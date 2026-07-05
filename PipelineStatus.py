#!/usr/bin/env python3
"""Small JSON status file for the JobHunter web status viewer."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


_LOCK = threading.Lock()
STATUS_PATH = Path(__file__).resolve().parent / "database" / "pipeline_status.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_status() -> Dict[str, Any]:
    if not STATUS_PATH.exists():
        return {}
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def update_status(**fields: Any) -> Dict[str, Any]:
    """Merge fields into the persisted status file and return the new state."""
    with _LOCK:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        status = read_status()
        status.update(fields)
        status["updated_at_utc"] = utc_now_iso()
        tmp_path = STATUS_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(status, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        tmp_path.replace(STATUS_PATH)
        return status


def append_event(event: str, **fields: Any) -> Dict[str, Any]:
    """Add a compact recent event for the status page."""
    status = read_status()
    events = list(status.get("events") or [])
    events.append({"event": event, "timestamp_utc": utc_now_iso(), **fields})
    return update_status(events=events[-80:])
