#!/usr/bin/env python3
"""
Job data schema and normalization helpers.

This module defines the normalized job dictionary structure and helper
functions used by scraper modules.
"""

import re
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


DEFAULT_LLM_COMMENT = "LLM didn't provide any comment"


JOB_DATA_TEMPLATE = {
    "job_title": "",
    "job_location": "",
    "job_description": "",
    "job_url": "",
    "date": "",
    "type": "",
    "isRemote": False,
    "salary": "",
    "company_name": "",
    "source": "",
    "LLMComment": DEFAULT_LLM_COMMENT,
    "raw_columns": [],
}


def _normalize_job_type(text: str) -> str:
    lowered = text.lower()
    if "intern" in lowered:
        return "intern"
    if "part" in lowered:
        return "part"
    if "full" in lowered:
        return "full"
    return ""


def _extract_salary(text: str) -> str:
    salary_pattern = r"(\$\s?[\d,]+(?:\s?-\s?\$\s?[\d,]+)?(?:\s?/\s?(?:hour|hr|year|yr))?)"
    match = re.search(salary_pattern, text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _is_remote_job(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in ["remote", "hybrid", "work from home"])


def build_job_data(
    *,
    job_title: str = "",
    job_location: str = "",
    job_description: str = "",
    job_url: str = "",
    date: str = "",
    job_type: str = "",
    is_remote: bool = False,
    salary: str = "",
    company_name: str = "",
    source: str = "UofT CUPE 3902",
    llm_comment: str = DEFAULT_LLM_COMMENT,
    raw_columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    data = dict(JOB_DATA_TEMPLATE)
    data.update(
        {
            "job_title": job_title,
            "job_location": job_location,
            "job_description": job_description,
            "job_url": job_url,
            "date": date,
            "type": _normalize_job_type(job_type),
            "isRemote": is_remote,
            "salary": salary,
            "company_name": company_name,
            "source": source,
            "LLMComment": llm_comment or DEFAULT_LLM_COMMENT,
            "raw_columns": raw_columns or [],
        }
    )
    return data

def parse_job_data(job_data: Dict[str, Any]) -> str:
    """Convert a normalized job dictionary into a single text block for LLM consumption."""
    if not isinstance(job_data, dict):
        raise TypeError("job_data must be a dict")

    title = str(job_data.get("job_title", "")).strip()
    company_name = str(job_data.get("company_name", "")).strip()
    location = str(job_data.get("job_location", "")).strip()
    description = str(job_data.get("job_description", "")).strip()
    url = str(job_data.get("job_url", "")).strip()
    date = str(job_data.get("date", "")).strip()
    job_type = str(job_data.get("type", "")).strip()
    salary = str(job_data.get("salary", "")).strip()
    source = str(job_data.get("source", "")).strip()
    raw_columns = job_data.get("raw_columns", [])

    raw_text = ""
    if isinstance(raw_columns, list):
        raw_text = "\n".join(str(item).strip() for item in raw_columns if item)
    elif raw_columns is not None:
        raw_text = str(raw_columns).strip()

    inferred_salary = salary or _extract_salary(description) or _extract_salary(raw_text)
    inferred_type = job_type or _normalize_job_type(" ".join([title, description, raw_text]))
    inferred_remote = bool(job_data.get("isRemote")) or _is_remote_job(" ".join([location, description, raw_text]))
    remote_text = "yes" if inferred_remote else "no"

    parts = []
    if title:
        parts.append(f"Job Title: {title}")
    if company_name:
        parts.append(f"Company Name: {company_name}")
    if location:
        parts.append(f"Location: {location}")
    if date:
        parts.append(f"Date Posted: {date}")
    if inferred_type:
        parts.append(f"Job Type: {inferred_type}")
    parts.append(f"Remote: {remote_text}")
    if inferred_salary:
        parts.append(f"Salary: {inferred_salary}")
    if url:
        parts.append(f"Job URL: {url}")
    if source:
        parts.append(f"Source: {source}")
    if description:
        parts.append(f"Job Description: {description}")
    if raw_text:
        parts.append(f"Raw Columns: {raw_text}")

    return "\n".join(parts)

def parse_json_to_job_reason_pairs(json_input: Any) -> List[List[Any]]:
    """
    Parse a JSON-format dataset (string or Python object) and return a list of
    [job, reasoning] pairs.

    Accepts:
    - a JSON string representing a list of objects
    - a Python list/dict as returned by json.loads or other code

    This function is tolerant of surrounding text, single dict inputs, and
    common key name variations (e.g. 'Job', 'job', 'id' and 'Reasoning',
    'reason', 'explanation').
    """
    import json as _json
    import ast as _ast
    import re as _re

    if json_input is None:
        return []

    def _to_list(obj: Any) -> List[Any]:
        if isinstance(obj, (list, tuple)):
            return list(obj)
        if isinstance(obj, dict):
            return [obj]
        if isinstance(obj, str):
            s = obj.strip()
            if not s:
                return []
            # try direct JSON parse
            try:
                return _json.loads(s)
            except Exception:
                pass
            # extract a JSON array substring if present
            m = _re.search(r'(\[.*\])', s, _re.S)
            if m:
                candidate = m.group(1)
                try:
                    return _json.loads(candidate)
                except Exception:
                    pass
            # fallback to Python literal parsing
            try:
                return _ast.literal_eval(s)
            except Exception as exc:
                raise ValueError("Could not parse input as JSON or Python literal") from exc
        raise TypeError("Unsupported input type for parse_json_to_job_reason_pairs")

    items = _to_list(json_input)
    pairs: List[List[Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        job_val = None
        reasoning_val = None
        for k, v in item.items():
            kl = str(k).strip().lower()
            if job_val is None and kl in ("job", "jobid", "id", "job_id"):
                job_val = v
            if reasoning_val is None and kl in ("reasoning", "reason", "explanation", "analysis", "notes"):
                reasoning_val = v
        # fallback: find any numeric-like value for job
        if job_val is None:
            for v in item.values():
                if isinstance(v, int):
                    job_val = v
                    break
                if isinstance(v, str) and v.isdigit():
                    job_val = int(v)
                    break
        # fallback for reasoning: first non-empty string field that's not the job
        if reasoning_val is None:
            for k, v in item.items():
                if str(k).strip().lower() in ("job", "jobid", "id", "job_id"):
                    continue
                if isinstance(v, str) and v.strip():
                    reasoning_val = v.strip()
                    break
        pairs.append([job_val, reasoning_val])

    return pairs


# --- Simple SQLite persistence helpers ---
DEFAULT_DB_FILENAME = "jobs.db"
DATABASE_DIRNAME = "database"


def get_database_dir() -> Path:
    db_dir = Path(__file__).resolve().parent / DATABASE_DIRNAME
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir

def get_default_db_path() -> str:
    return str(get_database_dir() / DEFAULT_DB_FILENAME)

def get_named_db_path(name: str, unwanted: bool = False) -> str:
    normalized_name = (name or "").strip()
    if not normalized_name:
        return get_default_db_path()

    suffix = "unwanted_jobs.db" if unwanted else "jobs.db"
    return str(get_database_dir() / f"{normalized_name}{suffix}")

def connect_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    db_path = db_path or get_default_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def create_jobs_table(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_title TEXT,
            job_location TEXT,
            job_description TEXT,
            job_url TEXT,
            date TEXT,
            type TEXT,
            isRemote INTEGER,
            salary TEXT,
            company_name TEXT,
            source TEXT,
            LLMComment TEXT,
            raw_columns TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_unique
        ON jobs (job_url, job_title, company_name, job_location)
        """
    )

    # Migrate existing table schema if needed
    cur.execute("PRAGMA table_info(jobs)")
    columns = [row[1] for row in cur.fetchall()]
    if "LLMComment" not in columns:
        cur.execute("ALTER TABLE jobs ADD COLUMN LLMComment TEXT")

    conn.commit()

def job_exists(conn: sqlite3.Connection, job_data: Dict[str, Any]) -> bool:
    cur = conn.cursor()
    job_url = (job_data.get("job_url") or "").strip()
    if job_url:
        cur.execute("SELECT 1 FROM jobs WHERE job_url = ? LIMIT 1", (job_url,))
        return cur.fetchone() is not None

    title = (job_data.get("job_title") or "").strip()
    company = (job_data.get("company_name") or "").strip()
    location = (job_data.get("job_location") or "").strip()
    cur.execute(
        "SELECT 1 FROM jobs WHERE job_title = ? AND company_name = ? AND job_location = ? LIMIT 1",
        (title, company, location),
    )
    return cur.fetchone() is not None

def add_job_to_db(job_data: Dict[str, Any], db_path: Optional[str] = None) -> bool:
    """
    Add a job to the SQLite database if it does not already exist.

    Returns True if the job was inserted, False if it was skipped because it exists.
    """
    conn = connect_db(db_path)
    try:
        create_jobs_table(conn)
        if job_exists(conn, job_data):
            return False

        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO jobs
            (job_title, job_location, job_description, job_url, date, type, isRemote, salary, company_name, source, LLMComment, raw_columns, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_data.get("job_title"),
                job_data.get("job_location"),
                job_data.get("job_description"),
                job_data.get("job_url"),
                job_data.get("date"),
                job_data.get("type"),
                1 if job_data.get("isRemote") else 0,
                job_data.get("salary"),
                job_data.get("company_name"),
                job_data.get("source"),
                job_data.get("LLMComment"),
                json.dumps(job_data.get("raw_columns", []), ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def _row_to_job_dict(row: sqlite3.Row) -> Dict[str, Any]:
    raw_columns = json.loads(row["raw_columns"]) if row["raw_columns"] else []
    return {
        "id": row["id"],
        "job_title": row["job_title"],
        "job_location": row["job_location"],
        "job_description": row["job_description"],
        "job_url": row["job_url"],
        "date": row["date"],
        "type": row["type"],
        "isRemote": bool(row["isRemote"]),
        "salary": row["salary"],
        "company_name": row["company_name"],
        "source": row["source"],
        "LLMComment": row["LLMComment"],
        "raw_columns": raw_columns,
        "created_at": row["created_at"],
    }


def get_jobs_after_timestamp(
    *,
    unix_timestamp: float,
    last_job_id: Optional[int] = None,
    db_path: Optional[str] = None,
    name: Optional[str] = None,
    unwanted: bool = False,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    if db_path is None and name:
        db_path = get_named_db_path(name, unwanted=unwanted)

    since_iso = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc).isoformat()

    conn = connect_db(db_path)
    try:
        cur = conn.cursor()
        create_jobs_table(conn)

        # Strictly advance beyond the last sent checkpoint to avoid re-announcing the
        # boundary row. When timestamps are equal, fall back to row id ordering.
        query = "SELECT * FROM jobs WHERE created_at > ?"
        params: List[Any] = [since_iso]

        if isinstance(last_job_id, int) and last_job_id > 0:
            query = (
                "SELECT * FROM jobs "
                "WHERE created_at > ? OR (created_at = ? AND id > ?)"
            )
            params = [since_iso, since_iso, last_job_id]

        query += " ORDER BY created_at ASC, id ASC"

        if isinstance(limit, int) and limit > 0:
            query += " LIMIT ?"
            params.append(limit)

        cur.execute(query, params)
        rows = cur.fetchall()
        return [_row_to_job_dict(row) for row in rows]
    finally:
        conn.close()

def get_all_jobs(
    db_path: Optional[str] = None,
    name: Optional[str] = None,
    unwanted: bool = False,
) -> List[Dict[str, Any]]:
    if db_path is None and name:
        db_path = get_named_db_path(name, unwanted=unwanted)

    conn = connect_db(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        rows = cur.fetchall()
        return [_row_to_job_dict(row) for row in rows]
    finally:
        conn.close()


