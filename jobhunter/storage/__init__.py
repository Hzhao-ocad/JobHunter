from jobhunter.storage.database import connect_db, get_database_dir, get_default_db_path, get_named_db_path
from jobhunter.storage.repositories import (
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
from jobhunter.storage.schema import create_jobs_table

__all__ = [
    "STATUS_NEW",
    "STATUS_RECOMMENDED",
    "STATUS_UNWANTED",
    "add_job_for_profile",
    "add_job_to_db",
    "connect_db",
    "create_jobs_table",
    "get_all_jobs",
    "get_database_dir",
    "get_default_db_path",
    "get_jobs_after_timestamp",
    "get_named_db_path",
    "job_exists",
    "mark_profile_jobs_status",
    "profile_job_exists",
    "upsert_profile",
]
