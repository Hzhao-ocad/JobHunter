"""Persistence operations for jobs, profiles, and profile job statuses."""

from __future__ import annotations

from jobhunter.jobs.struct import (
    STATUS_NEW,
    STATUS_RECOMMENDED,
    STATUS_UNWANTED,
    add_job_for_profile,
    add_job_to_db,
    get_all_jobs,
    get_jobs_after_timestamp,
    job_exists,
    mark_profile_jobs_status,
    profile_job_exists,
    upsert_profile,
)

__all__ = [
    "STATUS_NEW",
    "STATUS_RECOMMENDED",
    "STATUS_UNWANTED",
    "add_job_for_profile",
    "add_job_to_db",
    "get_all_jobs",
    "get_jobs_after_timestamp",
    "job_exists",
    "mark_profile_jobs_status",
    "profile_job_exists",
    "upsert_profile",
]

