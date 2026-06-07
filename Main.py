#!/usr/bin/env python3
"""Run the JobHunter pipeline using user needs from config."""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, time as day_time, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import LLMLayer


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "discord_config.json"
DEFAULT_RUN_TIMES = "03:00,08:00,11:00,14:00,14:27,17:00,22:00"


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


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Run JobHunter with config-driven user needs.")
	parser.add_argument(
		"--config",
		default=str(DEFAULT_CONFIG_PATH),
		help="Path to config JSON containing nameNeed. Default: discord_config.json",
	)
	parser.add_argument(
		"--times",
		default=DEFAULT_RUN_TIMES,
		help=(
			"Comma-separated 24-hour run times (HH:MM). "
			f"Default: {DEFAULT_RUN_TIMES}"
		),
	)
	parser.add_argument(
		"--once",
		action="store_true",
		help="Run one time immediately and exit.",
	)
	parser.add_argument(
		"--run-now",
		action="store_true",
		help="When running in schedule mode, run immediately before waiting for the next time.",
	)
	parser.add_argument(
		"--log-level",
		default="INFO",
		choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
		help="Logging verbosity. Default: INFO",
	)
	parser.add_argument(
		"--log-file",
		default="",
		help="Optional log file path. If set, logs are written to both console and file.",
	)
	return parser.parse_args()


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
	user_names, user_needs = load_user_needs(config_path)
	job_finder = LLMLayer.LLMClient()
	LLMLayer.FindMeSomeJobs(user_needs, user_names, job_finder)


def run_scheduler(config_path: Path, run_times: List[day_time], run_now: bool = False) -> None:
	logger = logging.getLogger(__name__)
	times_display = ", ".join(t.strftime("%H:%M") for t in run_times)
	logger.info("Scheduler started. Local run times: %s", times_display)

	if run_now:
		logger.info("Running immediately (--run-now).")
		try:
			run_pipeline_once(config_path)
		except Exception as exc:
			logger.exception("Immediate run failed: %s", exc)

	while True:
		now = datetime.now()
		next_run = _get_next_run(now, run_times)
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


def main() -> None:
	args = parse_args()
	_configure_logging(args.log_level, args.log_file)
	config_path = Path(args.config)
	_validate_config_path(config_path)

	if args.once:
		run_pipeline_once(config_path)
		return

	run_times = _parse_run_times(args.times)
	run_scheduler(config_path, run_times=run_times, run_now=args.run_now)


if __name__ == "__main__":
	main()