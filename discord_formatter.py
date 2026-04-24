#!/usr/bin/env python3
"""Formatting helpers for Discord job announcements."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

import discord


EMBED_COLOR = 0x1D4ED8
INVALID_TEXT_VALUES = {"nan", "none", "null", "n/a", "na"}


def _safe_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()
    if not text:
        return ""

    if text.lower() in INVALID_TEXT_VALUES:
        return ""

    return text


def _is_valid_http_url(value: str) -> bool:
    url = _safe_text(value)
    if not url:
        return False

    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)



def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    text = _safe_text(value)
    if not text:
        return None

    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def build_mention_text(role_ids: Optional[Iterable[int]] = None, user_ids: Optional[Iterable[int]] = None) -> str:
    mentions: List[str] = []

    for role_id in role_ids or []:
        try:
            mentions.append(f"<@&{int(role_id)}>")
        except (TypeError, ValueError):
            continue

    for user_id in user_ids or []:
        try:
            mentions.append(f"<@{int(user_id)}>")
        except (TypeError, ValueError):
            continue

    return " ".join(mentions)


def job_dedupe_key(job: Dict[str, Any]) -> str:
    url = _safe_text(job.get("job_url"))
    if url:
        return f"url:{url}"

    title = _safe_text(job.get("job_title"))
    company = _safe_text(job.get("company_name"))
    location = _safe_text(job.get("job_location"))
    created_at = _safe_text(job.get("created_at"))
    return f"fallback:{title}|{company}|{location}|{created_at}"


def build_job_embed(job: Dict[str, Any]) -> discord.Embed:
    title = _truncate(_safe_text(job.get("job_title")) or "Untitled Job", 256)
    company_name = _safe_text(job.get("company_name"))
    location = _safe_text(job.get("job_location"))
    is_remote = "Yes" if bool(job.get("isRemote")) else "No"

    description_parts = []
    if company_name:
        description_parts.append(company_name)
    if location:
        description_parts.append(location)
    description_parts.append(f"Remote: {is_remote}")

    embed = discord.Embed(
        title=title,
        description=_truncate(" | ".join(description_parts), 2048),
        color=EMBED_COLOR,
    )

    job_url = _safe_text(job.get("job_url"))
    if _is_valid_http_url(job_url):
        embed.url = job_url

    job_type = _safe_text(job.get("type")) or "N/A"
    salary = _safe_text(job.get("salary")) or "N/A"
    posted_date = _safe_text(job.get("date")) or "N/A"
    source = _safe_text(job.get("source")) or "Unknown"

    embed.add_field(name="Type", value=_truncate(job_type, 1024), inline=True)
    embed.add_field(name="Salary", value=_truncate(salary, 1024), inline=True)
    embed.add_field(name="Posted", value=_truncate(posted_date, 1024), inline=True)

    llm_comment = _safe_text(job.get("LLMComment"))
    if llm_comment:
        embed.add_field(name="Why it matched", value=_truncate(llm_comment, 300), inline=False)

    embed.set_footer(text=_truncate(f"JobHunter | Source: {source}", 2048))

    created_at = _parse_iso_datetime(_safe_text(job.get("created_at")))
    if created_at is not None:
        embed.timestamp = created_at

    return embed
