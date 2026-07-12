"""Default runtime settings for local JobHunter entrypoints."""

from __future__ import annotations

from jobhunter.paths import PROJECT_ROOT


DEFAULT_CONFIG_PATH = PROJECT_ROOT / "discord_config.json"
DEFAULT_RUN_TIMES = "03:00,08:00,10:42,11:00,14:00,14:27,17:00,22:00"
DEFAULT_STATUS_PORT = 8502

