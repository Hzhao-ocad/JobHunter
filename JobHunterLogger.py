#!/usr/bin/env python3
"""
JobHunter Centralized Logging System.

Provides structured, file-based logging for:
  1. Every job search result (per scraper source, with job count and metadata).
  2. DeepSeek API chat history (full messages + response per batch).
  3. Final filtered results (potential vs unwanted jobs per user).

All logs are written as JSON Lines (one JSON object per line) into a
timestamped run directory under `logs/`.  A separate human-readable
summary log is also maintained.

Usage (add to existing code without changing any logic):
    from JobHunterLogger import get_logger

    logger = get_logger()
    logger.log_job_search_results("GetGeneralJobs", all_jobs)
    logger.log_llm_chat(messages, response, user_name="Harry", batch_idx=0)
    logger.log_final_results("Harry", potential_jobs, unwanted_jobs)
"""

from __future__ import annotations

import atexit
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_LOG_DIR = Path(__file__).resolve().parent / "logs"

# Standard Python logger for operational messages from the logger itself.
_INTERNAL_LOGGER = logging.getLogger("JobHunter.Logger")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts_file() -> str:
    """Filesystem-safe timestamp for directory / file names."""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


# ---------------------------------------------------------------------------
# JSON Lines file writer (thread-safe)
# ---------------------------------------------------------------------------

class _JsonLinesWriter:
    """Append-only, thread-safe JSON Lines writer."""

    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path
        self._lock = threading.Lock()
        file_path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: Dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            with open(self._file_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()


# ---------------------------------------------------------------------------
# JobHunterLogger
# ---------------------------------------------------------------------------

class JobHunterLogger:
    """Central diagnostic logger for the JobHunter pipeline.

    Each call to :meth:`start_run` creates a new run directory under
    ``logs/`` with the pattern ``run_<timestamp>_<uuid8>``.  Within that
    directory the following JSON Lines files are created on demand:

    * ``job_search_results.jsonl``  – every scraper result set
    * ``llm_chat_history.jsonl``    – every LLM request/response pair
    * ``final_results.jsonl``       – per-user recommended + unwanted jobs
    * ``run_summary.log``           – human-readable plain-text summary
    """

    _instance: Optional["JobHunterLogger"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._run_id: str = ""
        self._run_dir: Optional[Path] = None
        self._writers: Dict[str, _JsonLinesWriter] = {}
        self._summary_path: Optional[Path] = None
        self._started: bool = False

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> "JobHunterLogger":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def start_run(self, run_id: Optional[str] = None) -> str:
        """Begin a new diagnostic run.

        Parameters:
            run_id: Optional stable identifier.  When omitted a UUID is
                    generated.  Useful for correlating with scheduler runs.

        Returns:
            The run_id string that can be used to query logs later.
        """
        if self._started:
            self._flush_all()

        self._run_id = run_id or f"{_ts_file()}_{uuid.uuid4().hex[:8]}"
        self._run_dir = _LOG_DIR / f"run_{self._run_id}"
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._writers = {}
        self._summary_path = self._run_dir / "run_summary.log"
        self._started = True

        # Write a header line to the summary log.
        header = (
            f"{'='*60}\n"
            f"JobHunter Diagnostic Run\n"
            f"Run ID  : {self._run_id}\n"
            f"Started : {_utc_iso()}\n"
            f"{'='*60}\n"
        )
        self._append_summary(header)
        _INTERNAL_LOGGER.info("Diagnostic run started: %s", self._run_id)
        return self._run_id

    def end_run(self) -> None:
        """Finalise the current run (flush + write footer)."""
        if not self._started:
            return
        footer = (
            f"\n{'='*60}\n"
            f"Run ended: {_utc_iso()}\n"
            f"{'='*60}\n"
        )
        self._append_summary(footer)
        self._flush_all()
        self._started = False
        _INTERNAL_LOGGER.info("Diagnostic run ended: %s", self._run_id)

    # ------------------------------------------------------------------
    # Job search results
    # ------------------------------------------------------------------

    def log_job_search_results(
        self,
        source: str,
        jobs: List[Dict[str, Any]],
        *,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log every job returned by a scraper.

        Parameters:
            source: Human-readable scraper name (e.g. ``"GetGeneralJobs"``).
            jobs:   The list of normalized job dicts returned by the scraper.
            extra:  Optional extra metadata (e.g. search terms, filters).
        """
        self._ensure_run()

        record: Dict[str, Any] = {
            "event": "job_search_results",
            "run_id": self._run_id,
            "timestamp_utc": _utc_iso(),
            "source": source,
            "job_count": len(jobs),
            "jobs": [
                self._summarize_job(j, idx) for idx, j in enumerate(jobs)
            ],
        }
        if extra:
            record["extra"] = extra

        self._write("job_search_results", record)
        self._append_summary(
            f"[{_utc_iso()}] SCRAPE | source={source} | jobs={len(jobs)}\n"
        )

    # ------------------------------------------------------------------
    # LLM chat history
    # ------------------------------------------------------------------

    def log_llm_chat(
        self,
        messages: List[Dict[str, str]],
        response: Any,
        *,
        user_name: str = "",
        batch_index: int = 0,
        model: str = "",
        provider: str = "",
    ) -> None:
        """Log a full LLM request/response exchange.

        Parameters:
            messages:    The message list sent to the LLM (including system prompt).
            response:    The raw response object (dict / parsed JSON).
            user_name:   Which user this chat session belongs to.
            batch_index: Which batch of jobs is being filtered.
            model:       LLM model name.
            provider:    LLM provider (e.g. "deepseek", "copilot").
        """
        self._ensure_run()

        # Extract just the content from the response for readability.
        response_content = ""
        response_error = None
        if isinstance(response, dict):
            response_error = response.get("error")
            try:
                response_content = response["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                response_content = json.dumps(response, ensure_ascii=False, default=str)

        record: Dict[str, Any] = {
            "event": "llm_chat",
            "run_id": self._run_id,
            "timestamp_utc": _utc_iso(),
            "user_name": user_name,
            "batch_index": batch_index,
            "model": model,
            "provider": provider,
            "messages": messages,
            "response_content": response_content,
            "response_error": response_error,
        }

        self._write("llm_chat_history", record)

        # Human-readable summary line.
        msg_count = len(messages)
        resp_len = len(response_content) if response_content else 0
        status = "ERR" if response_error else "OK"
        self._append_summary(
            f"[{_utc_iso()}] LLM    | user={user_name} | "
            f"batch={batch_index} | msgs={msg_count} | "
            f"resp_len={resp_len} | status={status} | "
            f"model={model} | provider={provider}\n"
        )

    # ------------------------------------------------------------------
    # Final results
    # ------------------------------------------------------------------

    def log_final_results(
        self,
        user_name: str,
        potential_jobs: List[Dict[str, Any]],
        unwanted_jobs: List[Dict[str, Any]],
        *,
        total_input_jobs: int = 0,
    ) -> None:
        """Log the final filtering verdict for one user.

        Parameters:
            user_name:        Name of the user.
            potential_jobs:   Jobs recommended by the LLM.
            unwanted_jobs:    Jobs not recommended.
            total_input_jobs: How many jobs were presented to the LLM.
        """
        self._ensure_run()

        record: Dict[str, Any] = {
            "event": "final_results",
            "run_id": self._run_id,
            "timestamp_utc": _utc_iso(),
            "user_name": user_name,
            "total_input_jobs": total_input_jobs,
            "potential_count": len(potential_jobs),
            "unwanted_count": len(unwanted_jobs),
            "potential_jobs": [
                self._summarize_job(j, idx) for idx, j in enumerate(potential_jobs)
            ],
            "unwanted_jobs": [
                self._summarize_job(j, idx) for idx, j in enumerate(unwanted_jobs)
            ],
        }

        self._write("final_results", record)
        self._append_summary(
            f"[{_utc_iso()}] RESULT | user={user_name} | "
            f"potential={len(potential_jobs)} | unwanted={len(unwanted_jobs)} | "
            f"total_input={total_input_jobs}\n"
        )

    # ------------------------------------------------------------------
    # Error logging
    # ------------------------------------------------------------------

    def log_error(
        self,
        component: str,
        error: str,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log an error that occurred during the pipeline."""
        self._ensure_run()
        record: Dict[str, Any] = {
            "event": "error",
            "run_id": self._run_id,
            "timestamp_utc": _utc_iso(),
            "component": component,
            "error": error,
        }
        if context:
            record["context"] = context

        self._write("job_search_results", record)  # reuse file for errors too
        self._append_summary(
            f"[{_utc_iso()}] ERROR  | component={component} | {error}\n"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_run(self) -> None:
        if not self._started:
            self.start_run()

    def _writer(self, name: str) -> _JsonLinesWriter:
        if name not in self._writers:
            assert self._run_dir is not None
            self._writers[name] = _JsonLinesWriter(
                self._run_dir / f"{name}.jsonl"
            )
        return self._writers[name]

    def _write(self, name: str, record: Dict[str, Any]) -> None:
        self._writer(name).write(record)

    def _append_summary(self, text: str) -> None:
        if self._summary_path is None:
            return
        with open(self._summary_path, "a", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()

    def _flush_all(self) -> None:
        """No-op – JSON Lines writers flush on every write."""
        pass

    @staticmethod
    def _summarize_job(job: Dict[str, Any], idx: int) -> Dict[str, Any]:
        """Return a compact, serializable summary of a job dict."""
        return {
            "index": idx,
            "job_title": str(job.get("job_title") or "").strip(),
            "company_name": str(job.get("company_name") or "").strip(),
            "job_location": str(job.get("job_location") or "").strip(),
            "job_url": str(job.get("job_url") or "").strip(),
            "source": str(job.get("source") or "").strip(),
            "LLMComment": str(job.get("LLMComment") or "").strip(),
        }


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_logger_instance: Optional[JobHunterLogger] = None


def get_logger() -> JobHunterLogger:
    """Return the singleton :class:`JobHunterLogger` instance."""
    return JobHunterLogger.instance()


def start_diagnostic_run(run_id: Optional[str] = None) -> str:
    """Convenience to start a new diagnostic run on the singleton logger."""
    return get_logger().start_run(run_id)


def end_diagnostic_run() -> None:
    """Convenience to end the current diagnostic run."""
    get_logger().end_run()


# Auto-flush on normal process exit.
atexit.register(lambda: get_logger().end_run())
