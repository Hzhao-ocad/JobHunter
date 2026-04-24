#!/usr/bin/env python3
"""Minimal Discord bot that announces new jobs from local SQLite DBs."""

from __future__ import annotations

import atexit
import argparse
import asyncio
import contextlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import discord

from JobStruct import get_jobs_after_timestamp
from discord_formatter import build_job_embed, build_mention_text, job_dedupe_key


LOGGER = logging.getLogger("discord_job_bot")
STATE_CACHE_SIZE = 200


@dataclass
class TargetConfig:
    name: str
    user_db_name: str
    guild_id: int
    channel_id: int
    role_ids: List[int] = field(default_factory=list)
    user_ids: List[int] = field(default_factory=list)
    enabled: bool = True
    max_jobs_per_poll: int = 25


@dataclass
class BotConfig:
    poll_interval_seconds: int
    message_rate_limit_seconds: float
    state_file: Path
    lock_file: Path
    targets: List[TargetConfig]
    config_path: Path
    name_need: Dict[str, Dict[str, str]] = field(default_factory=dict)


def _coerce_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid integer for '{field_name}': {value}") from exc


def _parse_iso_to_timestamp(value: str) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.timestamp()


def _normalize_name_need(raw_name_need: Any) -> Dict[str, Dict[str, str]]:
    """Normalize nameNeed into {discord_user_id: {name, need}}."""
    normalized: Dict[str, Dict[str, str]] = {}
    if not isinstance(raw_name_need, dict):
        return normalized

    for raw_user_id, raw_entry in raw_name_need.items():
        user_id = str(raw_user_id).strip()
        if not user_id:
            continue

        if isinstance(raw_entry, dict):
            name = str(raw_entry.get("name") or "").strip()
            need = str(raw_entry.get("need") or "").strip()
        elif isinstance(raw_entry, str):
            # Backward-compatible format: {"Name": "Need text"}
            name = user_id
            need = raw_entry.strip()
        else:
            continue

        if not name or not need:
            continue

        normalized[user_id] = {"name": name, "need": need}

    return normalized


def _serialize_name_need(name_need: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    serialized: Dict[str, Dict[str, str]] = {}
    for raw_user_id, raw_entry in sorted(name_need.items(), key=lambda item: str(item[0])):
        user_id = str(raw_user_id).strip()
        if not user_id or not isinstance(raw_entry, dict):
            continue

        name = str(raw_entry.get("name") or "").strip()
        need = str(raw_entry.get("need") or "").strip()
        if not name or not need:
            continue

        serialized[user_id] = {"name": name, "need": need}

    return serialized


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for line_number, raw_line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            LOGGER.warning("Skipping invalid env entry at %s:%s", env_path, line_number)
            continue

        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key:
            LOGGER.warning("Skipping empty env key at %s:%s", env_path, line_number)
            continue

        value = raw_value.strip()
        if value and value[0] in {"'", '"'} and value[-1] == value[0]:
            value = value[1:-1]

        os.environ.setdefault(key, value)


def load_config(config_path: Path) -> BotConfig:
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    config_dir = config_path.resolve().parent

    state_file = Path(raw.get("state_file", "database/discord_bot_state.json"))
    if not state_file.is_absolute():
        state_file = (config_dir / state_file).resolve()

    lock_file = Path(raw.get("lock_file", "database/discord_bot.lock"))
    if not lock_file.is_absolute():
        lock_file = (config_dir / lock_file).resolve()

    targets: List[TargetConfig] = []
    for index, target_raw in enumerate(raw.get("targets", [])):
        if not isinstance(target_raw, dict):
            raise ValueError(f"Target at index {index} must be an object")

        targets.append(
            TargetConfig(
                name=str(target_raw.get("name") or f"target-{index}").strip(),
                user_db_name=str(target_raw.get("user_db_name") or "").strip(),
                guild_id=_coerce_int(target_raw.get("guild_id"), f"targets[{index}].guild_id"),
                channel_id=_coerce_int(target_raw.get("channel_id"), f"targets[{index}].channel_id"),
                role_ids=[int(role_id) for role_id in target_raw.get("role_ids", [])],
                user_ids=[int(user_id) for user_id in target_raw.get("user_ids", [])],
                enabled=bool(target_raw.get("enabled", True)),
                max_jobs_per_poll=max(1, _coerce_int(target_raw.get("max_jobs_per_poll", 25), f"targets[{index}].max_jobs_per_poll")),
            )
        )

    if not targets:
        raise ValueError("Config must define at least one target in 'targets'")

    name_need = _normalize_name_need(raw.get("nameNeed", {}))

    return BotConfig(
        poll_interval_seconds=max(30, _coerce_int(raw.get("poll_interval_seconds", 300), "poll_interval_seconds")),
        message_rate_limit_seconds=max(0.0, float(raw.get("message_rate_limit_seconds", 1.5))),
        state_file=state_file,
        lock_file=lock_file,
        targets=targets,
        config_path=config_path.resolve(),
        name_need=name_need,
    )


def save_name_need_to_config(config: BotConfig) -> None:
    raw: Dict[str, Any] = {}
    if config.config_path.exists():
        try:
            loaded = json.loads(config.config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        except (OSError, json.JSONDecodeError):
            raw = {}

    raw["nameNeed"] = _serialize_name_need(config.name_need)

    config.config_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = config.config_path.with_suffix(config.config_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    temp_path.replace(config.config_path)


def _is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return False

        output = (result.stdout or "").strip()
        if not output or output.startswith("INFO:"):
            return False
        return f'"{pid}"' in output

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def acquire_single_instance_lock(lock_path: Path) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.exists():
        existing_pid = 0
        with contextlib.suppress(Exception):
            existing_pid = int(lock_path.read_text(encoding="utf-8").strip())

        if existing_pid and not _is_process_running(existing_pid):
            with contextlib.suppress(FileNotFoundError):
                lock_path.unlink()
        else:
            pid_text = str(existing_pid) if existing_pid else "unknown"
            raise RuntimeError(
                f"Another discord bot instance appears to be running (pid={pid_text}). "
                "Stop the existing process before starting a new one."
            )

    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("Another discord bot instance lock is active.") from exc

    try:
        os.write(fd, str(os.getpid()).encode("utf-8"))
    finally:
        os.close(fd)

    def _cleanup_lock() -> None:
        with contextlib.suppress(FileNotFoundError):
            lock_path.unlink()

    atexit.register(_cleanup_lock)


def load_state(state_path: Path) -> Dict[str, Any]:
    if not state_path.exists():
        return {"targets": {}}

    try:
        parsed = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("State file is invalid JSON. Starting with fresh state.")
        return {"targets": {}}

    if not isinstance(parsed, dict):
        return {"targets": {}}

    targets = parsed.get("targets")
    if not isinstance(targets, dict):
        parsed["targets"] = {}

    return parsed


def save_state(state_path: Path, state: Dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temp_path.replace(state_path)


def get_target_state(state: Dict[str, Any], target_name: str) -> Dict[str, Any]:
    targets = state.setdefault("targets", {})
    target_state = targets.setdefault(
        target_name,
        {
            "last_sent_timestamp": 0.0,
            "last_sent_job_id": 0,
            "recent_job_keys": [],
        },
    )

    if not isinstance(target_state.get("recent_job_keys"), list):
        target_state["recent_job_keys"] = []

    if not isinstance(target_state.get("last_sent_job_id"), int):
        try:
            target_state["last_sent_job_id"] = int(target_state.get("last_sent_job_id", 0))
        except (TypeError, ValueError):
            target_state["last_sent_job_id"] = 0

    return target_state


class JobAnnouncementBot(discord.Client):
    def __init__(self, *, config: BotConfig, state: Dict[str, Any], dry_run: bool):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents)

        self.config = config
        self.state = state
        self.dry_run = dry_run
        self._poll_task: Optional[asyncio.Task] = None
        self.tree = discord.app_commands.CommandTree(self)
        self._commands_registered = False
        self._config_write_lock = asyncio.Lock()

    async def setup_hook(self) -> None:
        self._register_slash_commands()
        await self._sync_slash_commands()
        self._poll_task = asyncio.create_task(self.poll_loop())

    def _register_slash_commands(self) -> None:
        if self._commands_registered:
            return

        @self.tree.command(name="need", description="Save your current job need text.")
        @discord.app_commands.describe(need="Describe what opportunities you want")
        async def need_command(
            interaction: discord.Interaction,
            need: discord.app_commands.Range[str, 1, 1800],
        ) -> None:
            await self._handle_need_command(interaction, need)

        @self.tree.command(name="myneed", description="Show your currently saved need text.")
        async def my_need_command(interaction: discord.Interaction) -> None:
            await self._handle_myneed_command(interaction)

        self._commands_registered = True

    async def _sync_slash_commands(self) -> None:
        guild_ids = sorted({target.guild_id for target in self.config.targets})
        for guild_id in guild_ids:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            LOGGER.info("Synced %s slash command(s) to guild %s", len(synced), guild_id)

    def _resolve_name_for_user(self, user: discord.abc.User) -> str:
        user_id = str(user.id)

        existing = self.config.name_need.get(user_id)
        if isinstance(existing, dict):
            existing_name = str(existing.get("name") or "").strip()
            if existing_name:
                return existing_name

        for target in self.config.targets:
            if user.id in target.user_ids:
                mapped_name = str(target.user_db_name or "").strip()
                if mapped_name:
                    return mapped_name

        display_name = str(getattr(user, "display_name", "") or "").strip()
        if display_name:
            return display_name

        username = str(getattr(user, "name", "") or "").strip()
        if username:
            return username

        return f"user-{user.id}"

    async def _handle_need_command(self, interaction: discord.Interaction, need: str) -> None:
        need_text = str(need or "").strip()
        if not need_text:
            await interaction.response.send_message(
                "Need text cannot be empty. Try /need with your details.",
                ephemeral=True,
            )
            return

        user_id = str(interaction.user.id)
        mapped_name = self._resolve_name_for_user(interaction.user)

        try:
            async with self._config_write_lock:
                self.config.name_need[user_id] = {"name": mapped_name, "need": need_text}
                save_name_need_to_config(self.config)
        except OSError:
            LOGGER.exception("Failed to persist nameNeed data to config")
            await interaction.response.send_message(
                "I could not save your need due to a config write error.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Saved. Name: {mapped_name}. Use /myneed to view your current need.",
            ephemeral=True,
        )

    async def _handle_myneed_command(self, interaction: discord.Interaction) -> None:
        user_id = str(interaction.user.id)
        entry = self.config.name_need.get(user_id)
        if not isinstance(entry, dict):
            await interaction.response.send_message(
                "No saved need found. Use /need <your need text> first.",
                ephemeral=True,
            )
            return

        name = str(entry.get("name") or self._resolve_name_for_user(interaction.user)).strip()
        need_text = str(entry.get("need") or "").strip()
        if not need_text:
            await interaction.response.send_message(
                "No saved need found. Use /need <your need text> first.",
                ephemeral=True,
            )
            return

        truncated_need = need_text if len(need_text) <= 1700 else (need_text[:1697] + "...")
        await interaction.response.send_message(
            f"Name: {name}\nNeed: {truncated_need}",
            ephemeral=True,
        )

    async def close(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
        await super().close()

    async def on_ready(self) -> None:
        user_display = f"{self.user} ({self.user.id})" if self.user else "unknown"
        LOGGER.info("Connected to Discord as %s", user_display)
        await self.validate_targets()

    async def validate_targets(self) -> None:
        for target in self.config.targets:
            if not target.enabled:
                continue

            channel = await self._resolve_text_channel(target.channel_id)
            if channel is None:
                raise RuntimeError(f"Channel {target.channel_id} is not accessible or not a text channel")

            if channel.guild.id != target.guild_id:
                LOGGER.warning(
                    "Target '%s' guild mismatch: config=%s actual=%s",
                    target.name,
                    target.guild_id,
                    channel.guild.id,
                )

            bot_member = channel.guild.get_member(self.user.id) if self.user else None
            if bot_member is None:
                LOGGER.warning("Could not resolve bot member for guild %s", channel.guild.id)
                continue

            permissions = channel.permissions_for(bot_member)
            if not permissions.send_messages:
                raise RuntimeError(f"Missing send_messages permission in channel {target.channel_id}")
            if not permissions.embed_links:
                raise RuntimeError(f"Missing embed_links permission in channel {target.channel_id}")

            if (target.role_ids or target.user_ids) and not permissions.mention_everyone:
                LOGGER.warning(
                    "Bot may not be able to mention all configured roles/users in channel %s."
                    " Ensure role mentionability or mention permissions.",
                    target.channel_id,
                )

    async def poll_loop(self) -> None:
        await self.wait_until_ready()

        while not self.is_closed():
            try:
                await self.run_poll_cycle()
            except Exception:
                LOGGER.exception("Poll cycle failed")

            await asyncio.sleep(self.config.poll_interval_seconds)

    async def run_poll_cycle(self) -> None:
        for target in self.config.targets:
            if not target.enabled:
                continue

            target_state = get_target_state(self.state, target.name)
            last_sent_timestamp = float(target_state.get("last_sent_timestamp", 0.0))
            last_sent_job_id = int(target_state.get("last_sent_job_id", 0))

            jobs = get_jobs_after_timestamp(
                unix_timestamp=last_sent_timestamp,
                last_job_id=last_sent_job_id,
                name=target.user_db_name,
                unwanted=False,
                limit=target.max_jobs_per_poll,
            )

            if not jobs:
                LOGGER.debug("No new jobs for target '%s'", target.name)
                continue

            channel = await self._resolve_text_channel(target.channel_id)
            if channel is None:
                LOGGER.warning("Skipping target '%s' because channel is unavailable", target.name)
                continue

            LOGGER.info("Found %s new jobs for target '%s'", len(jobs), target.name)
            await self._announce_target_jobs(channel, target, target_state, jobs)

    async def _announce_target_jobs(
        self,
        channel: discord.TextChannel,
        target: TargetConfig,
        target_state: Dict[str, Any],
        jobs: List[Dict[str, Any]],
    ) -> None:
        recent_keys = set(str(item) for item in target_state.get("recent_job_keys", []))
        jobs_to_send: List[tuple[Dict[str, Any], str]] = []

        for job in jobs:
            dedupe_key = job_dedupe_key(job)
            if dedupe_key in recent_keys:
                continue
            jobs_to_send.append((job, dedupe_key))

        if not jobs_to_send:
            LOGGER.debug("No unsent jobs remain for target '%s' after dedupe", target.name)
            return

        mention_text = build_mention_text(target.role_ids, target.user_ids)

        if mention_text:
            if self.dry_run:
                LOGGER.info("[DRY RUN] Mention text for '%s': %s", target.name, mention_text)
            else:
                await channel.send(
                    content=mention_text,
                    allowed_mentions=discord.AllowedMentions(roles=True, users=True, everyone=False),
                )
                await asyncio.sleep(self.config.message_rate_limit_seconds)

        for job, dedupe_key in jobs_to_send:

            if self.dry_run:
                LOGGER.info("[DRY RUN] Would announce: %s", job.get("job_title", "Untitled Job"))
                continue

            embed = build_job_embed(job)
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            await asyncio.sleep(self.config.message_rate_limit_seconds)

            recent_keys.add(dedupe_key)
            self._update_target_state_after_send(target_state, recent_keys, job)
            save_state(self.config.state_file, self.state)

    def _update_target_state_after_send(
        self,
        target_state: Dict[str, Any],
        recent_keys: set,
        job: Dict[str, Any],
    ) -> None:
        created_at = str(job.get("created_at") or "")
        sent_timestamp = _parse_iso_to_timestamp(created_at)
        try:
            sent_job_id = int(job.get("id") or 0)
        except (TypeError, ValueError):
            sent_job_id = 0

        current_last_timestamp = float(target_state.get("last_sent_timestamp", 0.0))
        current_last_job_id = int(target_state.get("last_sent_job_id", 0))

        if sent_timestamp is not None:
            if sent_timestamp > current_last_timestamp:
                target_state["last_sent_timestamp"] = sent_timestamp
                target_state["last_sent_job_id"] = sent_job_id
            elif sent_timestamp == current_last_timestamp and sent_job_id > current_last_job_id:
                target_state["last_sent_job_id"] = sent_job_id

        recent_list = list(recent_keys)
        if len(recent_list) > STATE_CACHE_SIZE:
            recent_list = recent_list[-STATE_CACHE_SIZE:]
        target_state["recent_job_keys"] = recent_list

    async def _resolve_text_channel(self, channel_id: int) -> Optional[discord.TextChannel]:
        channel = self.get_channel(channel_id)
        if channel is None:
            with contextlib.suppress(discord.DiscordException):
                channel = await self.fetch_channel(channel_id)

        if isinstance(channel, discord.TextChannel):
            return channel
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Announce new jobs to Discord.")
    parser.add_argument(
        "--config",
        default="discord_config.json",
        help="Path to bot config JSON. Default: discord_config.json",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to env file containing DISCORD_BOT_TOKEN. Default: .env",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run polling logic without sending to Discord.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config_path = Path(args.config)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. Copy discord_config.example.json to discord_config.json and fill IDs."
        )

    env_path = Path(args.env_file)
    if env_path.exists():
        _load_env_file(env_path)

    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN is not set. Add it to your environment or --env-file."
        )

    config = load_config(config_path)
    acquire_single_instance_lock(config.lock_file)
    state = load_state(config.state_file)

    bot = JobAnnouncementBot(config=config, state=state, dry_run=args.dry_run)
    bot.run(token)


if __name__ == "__main__":
    main()
