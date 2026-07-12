#!/usr/bin/env python3
"""Run one JobHunter pipeline pass."""

from __future__ import annotations

from jobhunter.config.settings import DEFAULT_CONFIG_PATH
from jobhunter.pipeline.runner import _configure_logging, run_pipeline_once


def main() -> None:
    _configure_logging("INFO")
    run_pipeline_once(DEFAULT_CONFIG_PATH)


if __name__ == "__main__":
    main()

