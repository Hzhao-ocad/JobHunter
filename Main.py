#!/usr/bin/env python3
"""Compatibility entrypoint for the reorganized JobHunter package."""

from jobhunter.pipeline.runner import *  # noqa: F401,F403
from jobhunter.pipeline.runner import main


if __name__ == "__main__":
    main()

