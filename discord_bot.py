#!/usr/bin/env python3
"""Compatibility entrypoint for the reorganized Discord bot."""

from jobhunter.discord.bot import *  # noqa: F401,F403
from jobhunter.discord.bot import main


if __name__ == "__main__":
    main()

