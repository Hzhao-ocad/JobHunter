#!/usr/bin/env python3
"""Run the JobHunter pipeline using user needs from config."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from datetime import datetime, time as day_time, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

from JobHunterLogger import get_logger, start_diagnostic_run, end_diagnostic_run
from PipelineStatus import append_event, update_status


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "discord_config.json"
DEFAULT_RUN_TIMES = "03:00,08:00,10:42,11:00,14:00,14:27,17:00,22:00"
DEFAULT_STATUS_PORT = 8502


def _normalize_name_need(raw_name_need: object) -> Dict[str, Dict[str, str]]:
	"""Normalize supported nameNeed formats into {key: {name, need}}."""
	normalized: Dict[str, Dict[str, str]] = {}
	if not isinstance(raw_name_need, dict):
		return normalized

	for raw_key, raw_value in raw_name_need.items():
		key = str(raw_key).strip()
		if not key:
			continue

		if isinstance(raw_value, dict):
			name = str(raw_value.get("name") or "").strip()
			need = str(raw_value.get("need") or "").strip()
		elif isinstance(raw_value, str):
			# Backward-compatible format: {"Name": "Need text"}
			name = key
			need = raw_value.strip()
		else:
			continue

		if not name or not need:
			continue

		normalized[key] = {"name": name, "need": need}

	return normalized


def load_user_needs(config_path: Path) -> Tuple[List[str], List[str]]:
	raw = json.loads(config_path.read_text(encoding="utf-8"))
	normalized = _normalize_name_need(raw.get("nameNeed", {}))
	if not normalized:
		raise ValueError(
			"No user needs found in config. Add entries to 'nameNeed' first. "
			"Example: \"nameNeed\": {\"4892...\": {\"name\": \"Harry\", \"need\": \"...\"}}"
		)

	# Use name as the DB identity and prefer Discord user-id keyed entries when duplicated.
	needs_by_name: Dict[str, str] = {}
	for key, entry in normalized.items():
		name = entry["name"]
		need = entry["need"]
		if name not in needs_by_name or key.isdigit():
			needs_by_name[name] = need

	user_names = list(needs_by_name.keys())
	user_needs = [needs_by_name[name] for name in user_names]
	return user_names, user_needs


def _configure_logging(level_name: str, log_file: str = "") -> None:
	level = getattr(logging, level_name.upper(), logging.INFO)
	handlers: List[logging.Handler] = [logging.StreamHandler()]
	if log_file.strip():
		handlers.append(logging.FileHandler(log_file.strip(), encoding="utf-8"))

	logging.basicConfig(
		level=level,
		format="%(asctime)s %(levelname)s %(name)s: %(message)s",
		handlers=handlers,
	)


def _validate_config_path(config_path: Path) -> None:
	if not config_path.exists():
		raise FileNotFoundError(
			f"Config file not found: {config_path}. Copy discord_config.example.json to discord_config.json and fill your values."
		)


def _parse_run_times(raw_times: str) -> List[day_time]:
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

	# De-duplicate and keep times ordered for predictable scheduling.
	unique = {(t.hour, t.minute): t for t in times}
	return sorted(unique.values(), key=lambda t: (t.hour, t.minute))


def _get_next_run(now: datetime, run_times: List[day_time]) -> datetime:
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


def run_pipeline_once(config_path: Path) -> None:
	import LLMLayer

	_diag_logger = get_logger()
	user_names, user_needs = load_user_needs(config_path)
	update_status(
		state="running",
		phase="starting",
		config_path=str(config_path),
		user_count=len(user_names),
		user_names=user_names,
		last_run_started_at=datetime.now().isoformat(),
		last_error="",
	)
	append_event("pipeline_started", user_count=len(user_names), user_names=user_names)
	_diag_logger.log_job_search_results(
		"PIPELINE_START",
		[],
		extra={
			"user_count": len(user_names),
			"user_names": user_names,
			"config_path": str(config_path),
		},
	)
	job_finder = LLMLayer.LLMClient()
	try:
		LLMLayer.FindMeSomeJobs(user_needs, user_names, job_finder)
	except Exception as exc:
		update_status(
			state="error",
			phase="failed",
			last_error=str(exc),
			last_run_finished_at=datetime.now().isoformat(),
		)
		append_event("pipeline_failed", error=str(exc))
		raise
	else:
		update_status(
			state="idle",
			phase="finished",
			last_run_finished_at=datetime.now().isoformat(),
			last_error="",
		)
		append_event("pipeline_finished", user_count=len(user_names))


def run_scheduler(config_path: Path, run_times: List[day_time], run_now: bool = False) -> None:
	logger = logging.getLogger(__name__)
	times_display = ", ".join(t.strftime("%H:%M") for t in run_times)
	logger.info("Scheduler started. Local run times: %s", times_display)
	update_status(
		state="scheduler_started",
		phase="waiting",
		config_path=str(config_path),
		run_times=[t.strftime("%H:%M") for t in run_times],
		last_error="",
	)

	if run_now:
		logger.info("Running immediately (--run-now).")
		try:
			run_pipeline_once(config_path)
		except Exception as exc:
			logger.exception("Immediate run failed: %s", exc)

	while True:
		now = datetime.now()
		next_run = _get_next_run(now, run_times)
		update_status(
			state="waiting",
			phase="scheduled_wait",
			next_run_at=next_run.isoformat(),
			run_times=[t.strftime("%H:%M") for t in run_times],
		)
		logger.info(
			"Now: %s | Next run at: %s",
			now.strftime("%Y-%m-%d %H:%M:%S"),
			next_run.strftime("%Y-%m-%d %H:%M:%S"),
		)

		# Sleep in short intervals for robustness against clock adjustments and interrupts.
		while True:
			remaining = (next_run - datetime.now()).total_seconds()
			if remaining <= 0:
				break
			time.sleep(min(remaining, 60.0))

		logger.info("Running scheduled job...")
		try:
			run_pipeline_once(config_path)
			logger.info("Scheduled job finished.")
		except Exception as exc:
			logger.exception("Scheduled job failed: %s", exc)


def launch_status_viewer(port: int = DEFAULT_STATUS_PORT) -> None:
	viewer_path = Path(__file__).resolve().parent / "StatusViewer_UI.py"
	subprocess.run(
		[
			sys.executable,
			"-m",
			"streamlit",
			"run",
			str(viewer_path),
			"--server.port",
			str(port),
		],
		check=False,
	)


def main() -> None:
	_configure_logging("INFO")
	config_path = DEFAULT_CONFIG_PATH
	_validate_config_path(config_path)
	run_times = _parse_run_times(DEFAULT_RUN_TIMES)

	update_status(
		state="starting",
		phase="launching_viewer_and_scheduler",
		config_path=str(config_path),
		run_times=[t.strftime("%H:%M") for t in run_times],
		status_port=DEFAULT_STATUS_PORT,
		last_error="",
	)

	scheduler_thread = threading.Thread(
		target=run_scheduler,
		args=(config_path, run_times),
		kwargs={"run_now": True},
		name="JobHunterScheduler",
		daemon=True,
	)
	scheduler_thread.start()

	launch_status_viewer(DEFAULT_STATUS_PORT)


if __name__ == "__main__":
	main()
