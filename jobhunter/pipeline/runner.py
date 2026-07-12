#!/usr/bin/env python3
"""Run the JobHunter pipeline using user needs from config."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from datetime import datetime, time as day_time
from pathlib import Path
from typing import Dict, List, Tuple

from jobhunter.config.profiles import load_user_needs as _load_user_needs
from jobhunter.config.profiles import normalize_name_need
from jobhunter.config.settings import DEFAULT_CONFIG_PATH, DEFAULT_RUN_TIMES, DEFAULT_STATUS_PORT
from jobhunter.observability.diagnostic_logger import get_logger
from jobhunter.pipeline.scheduler import get_next_run, parse_run_times
from jobhunter.pipeline.status_store import append_event, update_status

_parse_run_times = parse_run_times
_get_next_run = get_next_run


def _normalize_name_need(raw_name_need: object) -> Dict[str, Dict[str, str]]:
	return normalize_name_need(raw_name_need)


def load_user_needs(config_path: Path) -> Tuple[List[str], List[str]]:
	return _load_user_needs(config_path)


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
	return parse_run_times(raw_times)


def _get_next_run(now: datetime, run_times: List[day_time]) -> datetime:
	return get_next_run(now, run_times)


def run_pipeline_once(config_path: Path) -> None:
	from jobhunter.llm import client as LLMLayer

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
	viewer_path = Path(__file__).resolve().parents[1] / "ui" / "status_dashboard.py"
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
