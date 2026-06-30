#!/usr/bin/env python3
"""
Job data schema, normalization helpers, and SQLite persistence.

The persistence layer uses one shared SQLite database:

- jobs: one canonical row per scraped job
- profiles: one row per person/profile
- profile_jobs: profile-specific status and LLM comment for each job
"""

import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


DEFAULT_LLM_COMMENT = "LLM didn't provide any comment"
LOG_PREFIX = "[JobHunter LOG]"
_LOGGER = logging.getLogger("JobHunter.JobStruct")


def _emit_log(level: int, message: str, *args: Any) -> None:
    """Emit a prefixed log line and fallback to print when logging is unconfigured."""
    rendered = message % args if args else message
    prefixed = f"{LOG_PREFIX} {rendered}"

    root_logger = logging.getLogger()
    if _LOGGER.handlers or root_logger.handlers:
        _LOGGER.log(level, prefixed)
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} {prefixed}", flush=True)


def _summarize_job(job_data: Dict[str, Any]) -> str:
    title = str(job_data.get("job_title") or "").strip() or "<no title>"
    company = str(job_data.get("company_name") or "").strip() or "<no company>"
    location = str(job_data.get("job_location") or "").strip() or "<no location>"
    url = str(job_data.get("job_url") or "").strip() or "<no url>"
    return f"title='{title}', company='{company}', location='{location}', url='{url}'"


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
    _emit_log(logging.DEBUG, "Normalized job record: %s", _summarize_job(data))
    return data


def parse_job_data(job_data: Dict[str, Any]) -> str:
    """Convert a normalized job dictionary into a single text block for LLM consumption."""
    if not isinstance(job_data, dict):
        _emit_log(logging.ERROR, "parse_job_data rejected non-dict input of type %s", type(job_data).__name__)
        raise TypeError("job_data must be a dict")

    _emit_log(logging.DEBUG, "Preparing LLM text for job: %s", _summarize_job(job_data))

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

    parsed = "\n".join(parts)
    _emit_log(logging.DEBUG, "Prepared LLM text with %d fields", len(parts))
    return parsed


def parse_json_to_job_reason_pairs(json_input: Any) -> List[List[Any]]:
    """
    Parse a JSON-format dataset and return [job, reasoning] pairs.

    Accepts JSON strings, Python lists/dicts, and common key variations such as
    Job/job/id plus Reasoning/reason/explanation.
    """
    import ast as _ast
    import json as _json
    import re as _re

    _emit_log(logging.INFO, "Parsing job-reason pairs from input type %s", type(json_input).__name__)

    if json_input is None:
        _emit_log(logging.WARNING, "Received empty json_input for job-reason parsing")
        return []

    def _to_list(obj: Any) -> List[Any]:
        if isinstance(obj, (list, tuple)):
            return list(obj)
        if isinstance(obj, dict):
            return [obj]
        if isinstance(obj, str):
            text = obj.strip()
            if not text:
                return []
            try:
                return _json.loads(text)
            except Exception:
                pass
            match = _re.search(r"(\[.*\])", text, _re.S)
            if match:
                try:
                    return _json.loads(match.group(1))
                except Exception:
                    pass
            try:
                return _ast.literal_eval(text)
            except Exception as exc:
                _emit_log(logging.ERROR, "Failed to parse job-reason input as JSON or Python literal")
                raise ValueError("Could not parse input as JSON or Python literal") from exc
        raise TypeError("Unsupported input type for parse_json_to_job_reason_pairs")

    items = _to_list(json_input)
    pairs: List[List[Any]] = []
    for item in items:
        if not isinstance(item, dict):
            _emit_log(logging.DEBUG, "Skipping non-dict item in job-reason list: %s", type(item).__name__)
            continue
        job_val = None
        reasoning_val = None
        for key, value in item.items():
            lowered_key = str(key).strip().lower()
            if job_val is None and lowered_key in ("job", "jobid", "id", "job_id"):
                job_val = value
            if reasoning_val is None and lowered_key in ("reasoning", "reason", "explanation", "analysis", "notes"):
                reasoning_val = value
        if job_val is None:
            for value in item.values():
                if isinstance(value, int):
                    job_val = value
                    break
                if isinstance(value, str) and value.isdigit():
                    job_val = int(value)
                    break
        if reasoning_val is None:
            for key, value in item.items():
                if str(key).strip().lower() in ("job", "jobid", "id", "job_id"):
                    continue
                if isinstance(value, str) and value.strip():
                    reasoning_val = value.strip()
                    break
        pairs.append([job_val, reasoning_val])

    _emit_log(logging.INFO, "Parsed %d job-reason pairs", len(pairs))
    return pairs


# --- SQLite persistence helpers ---
DEFAULT_DB_FILENAME = "jobhunter.db"
DATABASE_DIRNAME = "database"
STATUS_NEW = "new"
STATUS_RECOMMENDED = "recommended"
STATUS_UNWANTED = "unwanted"
VALID_PROFILE_JOB_STATUSES = {STATUS_NEW, STATUS_RECOMMENDED, STATUS_UNWANTED}


def get_database_dir() -> Path:
    db_dir = Path(__file__).resolve().parent / DATABASE_DIRNAME
    db_dir.mkdir(parents=True, exist_ok=True)
    _emit_log(logging.DEBUG, "Ensured database directory exists at %s", db_dir)
    return db_dir


def get_default_db_path() -> str:
    path = str(get_database_dir() / DEFAULT_DB_FILENAME)
    _emit_log(logging.DEBUG, "Resolved default DB path: %s", path)
    return path


def get_named_db_path(name: str, unwanted: bool = False) -> str:
    _emit_log(logging.DEBUG, "Named DB paths are deprecated; using shared DB for name=%s unwanted=%s", name, unwanted)
    return get_default_db_path()


def connect_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    db_path = db_path or get_default_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    _emit_log(logging.INFO, "Opening DB connection: %s", db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def compute_dedupe_key(job_data: Dict[str, Any]) -> str:
    """Produce a stable, normalized deduplication key from core job identity fields."""
    title = str(job_data.get("job_title") or "").strip().lower()
    company = str(job_data.get("company_name") or "").strip().lower()
    location = str(job_data.get("job_location") or "").strip().lower()
    normalized = f"{title}|{company}|{location}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _validate_profile_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized not in VALID_PROFILE_JOB_STATUSES:
        raise ValueError(
            f"Invalid profile job status '{status}'. "
            f"Expected one of: {', '.join(sorted(VALID_PROFILE_JOB_STATUSES))}"
        )
    return normalized


def _normalize_profile_name(name: Optional[str]) -> str:
    normalized = str(name or "").strip()
    if not normalized:
        raise ValueError("profile name is required")
    return normalized


def create_jobs_table(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    _emit_log(logging.DEBUG, "Ensuring shared jobs schema and indexes exist")
    cur.execute("PRAGMA foreign_keys = ON")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            discord_user_id TEXT,
            need TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
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
            raw_columns TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            dedupe_key TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS profile_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('new', 'recommended', 'unwanted')),
            LLMComment TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            pushed_at TEXT,
            UNIQUE (profile_id, job_id),
            FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
        """
    )
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_dedupe_key ON jobs (dedupe_key)")
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_url
        ON jobs (job_url)
        WHERE job_url IS NOT NULL AND job_url != ''
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_profiles_name ON profiles (name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_jobs_profile_status ON profile_jobs (profile_id, status, created_at, id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_profile_jobs_job ON profile_jobs (job_id)")
    conn.commit()
    if _is_default_db_connection(conn):
        _migrate_legacy_user_databases(conn)
    _emit_log(logging.DEBUG, "shared jobs schema setup complete")


def _get_profile_id(
    conn: sqlite3.Connection,
    name: str,
    *,
    discord_user_id: Optional[str] = None,
    need: Optional[str] = None,
) -> int:
    profile_name = _normalize_profile_name(name)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO profiles (name, discord_user_id, need, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            discord_user_id = COALESCE(excluded.discord_user_id, profiles.discord_user_id),
            need = COALESCE(excluded.need, profiles.need),
            updated_at = excluded.updated_at
        """,
        (profile_name, discord_user_id, need, now, now),
    )
    cur.execute("SELECT id FROM profiles WHERE name = ?", (profile_name,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"Failed to resolve profile id for {profile_name}")
    return int(row["id"])


def upsert_profile(
    name: str,
    *,
    discord_user_id: Optional[str] = None,
    need: Optional[str] = None,
    db_path: Optional[str] = None,
) -> int:
    conn = connect_db(db_path)
    try:
        create_jobs_table(conn)
        profile_id = _get_profile_id(conn, name, discord_user_id=discord_user_id, need=need)
        conn.commit()
        return profile_id
    finally:
        conn.close()


def _find_job_id(conn: sqlite3.Connection, job_data: Dict[str, Any]) -> Optional[int]:
    cur = conn.cursor()
    job_url = str(job_data.get("job_url") or "").strip()
    if job_url:
        cur.execute("SELECT id FROM jobs WHERE job_url = ? LIMIT 1", (job_url,))
        row = cur.fetchone()
        if row is not None:
            return int(row["id"])

    dedupe_key = compute_dedupe_key(job_data)
    cur.execute("SELECT id FROM jobs WHERE dedupe_key = ? LIMIT 1", (dedupe_key,))
    row = cur.fetchone()
    if row is not None:
        return int(row["id"])
    return None


def _upsert_job(conn: sqlite3.Connection, job_data: Dict[str, Any]) -> int:
    found_id = _find_job_id(conn, job_data)
    now = datetime.now(timezone.utc).isoformat()
    raw_columns = json.dumps(job_data.get("raw_columns", []), ensure_ascii=False)
    dedupe_key = compute_dedupe_key(job_data)
    cur = conn.cursor()

    if found_id is not None:
        cur.execute(
            """
            UPDATE jobs SET
                job_title = COALESCE(NULLIF(?, ''), job_title),
                job_location = COALESCE(NULLIF(?, ''), job_location),
                job_description = COALESCE(NULLIF(?, ''), job_description),
                job_url = COALESCE(NULLIF(?, ''), job_url),
                date = COALESCE(NULLIF(?, ''), date),
                type = COALESCE(NULLIF(?, ''), type),
                isRemote = ?,
                salary = COALESCE(NULLIF(?, ''), salary),
                company_name = COALESCE(NULLIF(?, ''), company_name),
                source = COALESCE(NULLIF(?, ''), source),
                raw_columns = COALESCE(NULLIF(?, '[]'), raw_columns),
                updated_at = ?
            WHERE id = ?
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
                raw_columns,
                now,
                found_id,
            ),
        )
        return found_id

    try:
        cur.execute(
            """
            INSERT INTO jobs
            (job_title, job_location, job_description, job_url, date, type, isRemote, salary, company_name, source, raw_columns, created_at, updated_at, dedupe_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                raw_columns,
                now,
                now,
                dedupe_key,
            ),
        )
        return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        found_id = _find_job_id(conn, job_data)
        if found_id is None:
            raise
        return found_id


def _insert_or_update_profile_job(
    conn: sqlite3.Connection,
    *,
    profile_id: int,
    job_id: int,
    status: str,
    llm_comment: Optional[str],
) -> bool:
    normalized_status = _validate_profile_status(status)
    now = datetime.now(timezone.utc).isoformat()
    pushed_at = now if normalized_status == STATUS_RECOMMENDED else None
    cur = conn.cursor()
    cur.execute(
        """
        SELECT status, COALESCE(LLMComment, '') AS LLMComment
        FROM profile_jobs
        WHERE profile_id = ? AND job_id = ?
        """,
        (profile_id, job_id),
    )
    existing = cur.fetchone()
    if existing is not None:
        existing_comment = str(existing["LLMComment"] or "")
        next_comment = llm_comment if llm_comment is not None else existing_comment
        if existing["status"] == normalized_status and existing_comment == str(next_comment or ""):
            return False
        cur.execute(
            """
            UPDATE profile_jobs
            SET status = ?, LLMComment = ?, updated_at = ?,
                pushed_at = CASE WHEN ? = 'recommended' THEN COALESCE(pushed_at, ?) ELSE pushed_at END
            WHERE profile_id = ? AND job_id = ?
            """,
            (normalized_status, next_comment, now, normalized_status, now, profile_id, job_id),
        )
        return True

    cur.execute(
        """
        INSERT INTO profile_jobs
        (profile_id, job_id, status, LLMComment, created_at, updated_at, pushed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (profile_id, job_id, normalized_status, llm_comment, now, now, pushed_at),
    )
    return True


def add_job_for_profile(
    job_data: Dict[str, Any],
    *,
    profile_name: str,
    status: str = STATUS_NEW,
    db_path: Optional[str] = None,
) -> bool:
    _emit_log(logging.INFO, "Adding profile job status=%s profile=%s: %s", status, profile_name, _summarize_job(job_data))
    conn = connect_db(db_path)
    try:
        create_jobs_table(conn)
        profile_id = _get_profile_id(conn, profile_name)
        job_id = _upsert_job(conn, job_data)
        changed = _insert_or_update_profile_job(
            conn,
            profile_id=profile_id,
            job_id=job_id,
            status=status,
            llm_comment=job_data.get("LLMComment"),
        )
        conn.commit()
        return changed
    finally:
        conn.close()


def job_exists(conn: sqlite3.Connection, job_data: Dict[str, Any]) -> bool:
    _emit_log(logging.DEBUG, "Checking duplicate job: %s", _summarize_job(job_data))
    create_jobs_table(conn)
    exists = _find_job_id(conn, job_data) is not None
    _emit_log(logging.DEBUG, "Global duplicate check returned %s", exists)
    return exists


def profile_job_exists(
    conn: sqlite3.Connection,
    profile_name: str,
    job_data: Dict[str, Any],
    *,
    statuses: Optional[Sequence[str]] = None,
) -> bool:
    create_jobs_table(conn)
    job_id = _find_job_id(conn, job_data)
    if job_id is None:
        return False

    profile_id = _get_profile_id(conn, profile_name)
    params: List[Any] = [profile_id, job_id]
    status_clause = ""
    if statuses:
        normalized_statuses = [_validate_profile_status(status) for status in statuses]
        status_clause = f" AND status IN ({','.join('?' for _ in normalized_statuses)})"
        params.extend(normalized_statuses)

    cur = conn.cursor()
    cur.execute(
        f"SELECT 1 FROM profile_jobs WHERE profile_id = ? AND job_id = ?{status_clause} LIMIT 1",
        params,
    )
    return cur.fetchone() is not None


def _legacy_profile_from_db_path(db_path: Optional[str]) -> tuple[Optional[str], str]:
    if not db_path:
        return None, STATUS_NEW

    filename = Path(db_path).name
    if filename == DEFAULT_DB_FILENAME:
        return None, STATUS_NEW
    if filename.endswith("unwanted_jobs.db"):
        return filename[: -len("unwanted_jobs.db")], STATUS_UNWANTED
    if filename.endswith("jobs.db"):
        return filename[: -len("jobs.db")], STATUS_NEW
    return None, STATUS_NEW


def add_job_to_db(
    job_data: Dict[str, Any],
    db_path: Optional[str] = None,
    *,
    profile_name: Optional[str] = None,
    status: str = STATUS_NEW,
) -> bool:
    """
    Add a job to the shared SQLite database for a profile.

    Returns True if a profile/job row was inserted or changed, False if it was
    already present with the same status and comment.
    """
    legacy_profile_name, legacy_status = _legacy_profile_from_db_path(db_path)
    resolved_profile_name = profile_name or legacy_profile_name
    resolved_status = legacy_status if profile_name is None and legacy_profile_name is not None else status
    if not resolved_profile_name:
        raise ValueError("profile_name is required when adding a job to the shared DB")

    target_db_path = get_default_db_path() if profile_name is None and legacy_profile_name is not None else db_path
    return add_job_for_profile(
        job_data,
        profile_name=resolved_profile_name,
        status=resolved_status,
        db_path=target_db_path,
    )


def _safe_load_raw_columns(value: Any) -> List[Any]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else [parsed]
    except (TypeError, json.JSONDecodeError):
        return [str(value)]


def _row_to_job_dict(row: sqlite3.Row) -> Dict[str, Any]:
    keys = set(row.keys())
    raw_columns = _safe_load_raw_columns(row["raw_columns"]) if "raw_columns" in keys else []
    profile_job_id = row["profile_job_id"] if "profile_job_id" in keys else None
    job_id = row["job_id"] if "job_id" in keys else row["id"]
    return {
        "id": profile_job_id if profile_job_id is not None else job_id,
        "job_id": job_id,
        "profile_job_id": profile_job_id,
        "profile_name": row["profile_name"] if "profile_name" in keys else None,
        "status": row["status"] if "status" in keys else None,
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
        "LLMComment": row["LLMComment"] if "LLMComment" in keys else DEFAULT_LLM_COMMENT,
        "raw_columns": raw_columns,
        "created_at": row["created_at"],
        "job_created_at": row["job_created_at"] if "job_created_at" in keys else row["created_at"],
        "updated_at": row["updated_at"] if "updated_at" in keys else None,
        "pushed_at": row["pushed_at"] if "pushed_at" in keys else None,
        "dedupe_key": row["dedupe_key"],
    }


def _profile_jobs_select_sql() -> str:
    return """
        SELECT
            pj.id AS profile_job_id,
            j.id AS job_id,
            p.name AS profile_name,
            pj.status AS status,
            j.job_title,
            j.job_location,
            j.job_description,
            j.job_url,
            j.date,
            j.type,
            j.isRemote,
            j.salary,
            j.company_name,
            j.source,
            pj.LLMComment AS LLMComment,
            j.raw_columns,
            pj.created_at AS created_at,
            j.created_at AS job_created_at,
            pj.updated_at AS updated_at,
            pj.pushed_at AS pushed_at,
            j.dedupe_key
        FROM profile_jobs pj
        JOIN profiles p ON p.id = pj.profile_id
        JOIN jobs j ON j.id = pj.job_id
    """


def get_jobs_after_timestamp(
    *,
    unix_timestamp: float = 0.0,
    since_iso: Optional[str] = None,
    last_job_id: Optional[int] = None,
    db_path: Optional[str] = None,
    name: Optional[str] = None,
    unwanted: bool = False,
    status: Optional[str] = STATUS_NEW,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    _emit_log(
        logging.INFO,
        "Fetching jobs after since_iso=%s, unix_timestamp=%s, last_job_id=%s, name=%s, unwanted=%s, status=%s, limit=%s",
        since_iso,
        unix_timestamp,
        last_job_id,
        name,
        unwanted,
        status,
        limit,
    )
    if unwanted:
        status = STATUS_UNWANTED

    since_iso_value = since_iso or datetime.fromtimestamp(unix_timestamp, tz=timezone.utc).isoformat()
    conn = connect_db(db_path)
    try:
        cur = conn.cursor()
        create_jobs_table(conn)

        query = _profile_jobs_select_sql()
        filters: List[str] = []
        params: List[Any] = []

        if name:
            filters.append("p.name = ?")
            params.append(_normalize_profile_name(name))
        if status:
            filters.append("pj.status = ?")
            params.append(_validate_profile_status(status))
        if since_iso or unix_timestamp:
            if isinstance(last_job_id, int) and last_job_id > 0:
                filters.append("(pj.created_at > ? OR (pj.created_at = ? AND pj.id > ?))")
                params.extend([since_iso_value, since_iso_value, last_job_id])
            else:
                filters.append("pj.created_at > ?")
                params.append(since_iso_value)
        if filters:
            query += " WHERE " + " AND ".join(filters)

        query += " ORDER BY pj.created_at ASC, pj.id ASC"
        if isinstance(limit, int) and limit > 0:
            query += " LIMIT ?"
            params.append(limit)

        cur.execute(query, params)
        rows = cur.fetchall()
        jobs = [_row_to_job_dict(row) for row in rows]
        _emit_log(logging.INFO, "Fetched %d jobs from incremental query", len(jobs))
        return jobs
    finally:
        _emit_log(logging.DEBUG, "Closing DB connection after get_jobs_after_timestamp")
        conn.close()


def get_all_jobs(
    db_path: Optional[str] = None,
    name: Optional[str] = None,
    unwanted: bool = False,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    _emit_log(logging.INFO, "Fetching all jobs (name=%s, unwanted=%s, status=%s)", name, unwanted, status)
    if unwanted:
        status = STATUS_UNWANTED

    conn = connect_db(db_path)
    try:
        cur = conn.cursor()
        create_jobs_table(conn)
        if name or status:
            query = _profile_jobs_select_sql()
            filters: List[str] = []
            params: List[Any] = []
            if name:
                filters.append("p.name = ?")
                params.append(_normalize_profile_name(name))
            if status:
                filters.append("pj.status = ?")
                params.append(_validate_profile_status(status))
            if filters:
                query += " WHERE " + " AND ".join(filters)
            query += " ORDER BY pj.created_at DESC, pj.id DESC"
            cur.execute(query, params)
        else:
            cur.execute(
                """
                SELECT
                    NULL AS profile_job_id,
                    j.id AS job_id,
                    NULL AS profile_name,
                    NULL AS status,
                    j.job_title,
                    j.job_location,
                    j.job_description,
                    j.job_url,
                    j.date,
                    j.type,
                    j.isRemote,
                    j.salary,
                    j.company_name,
                    j.source,
                    NULL AS LLMComment,
                    j.raw_columns,
                    j.created_at AS created_at,
                    j.created_at AS job_created_at,
                    j.updated_at AS updated_at,
                    NULL AS pushed_at,
                    j.dedupe_key
                FROM jobs j
                ORDER BY j.created_at DESC, j.id DESC
                """
            )
        rows = cur.fetchall()
        jobs = [_row_to_job_dict(row) for row in rows]
        _emit_log(logging.INFO, "Fetched %d total jobs", len(jobs))
        return jobs
    finally:
        _emit_log(logging.DEBUG, "Closing DB connection after get_all_jobs")
        conn.close()


def mark_profile_jobs_status(
    *,
    profile_name: str,
    profile_job_ids: Sequence[int],
    status: str,
    db_path: Optional[str] = None,
) -> int:
    normalized_status = _validate_profile_status(status)
    ids: List[int] = []
    for item in profile_job_ids:
        try:
            item_id = int(item)
        except (TypeError, ValueError):
            continue
        if item_id > 0:
            ids.append(item_id)
    if not ids:
        return 0

    conn = connect_db(db_path)
    try:
        create_jobs_table(conn)
        profile_id = _get_profile_id(conn, profile_name)
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in ids)
        pushed_sql = ", pushed_at = COALESCE(pushed_at, ?)" if normalized_status == STATUS_RECOMMENDED else ""
        params: List[Any] = [normalized_status, now]
        if normalized_status == STATUS_RECOMMENDED:
            params.append(now)
        params.extend([profile_id, *ids])
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE profile_jobs
            SET status = ?, updated_at = ?{pushed_sql}
            WHERE profile_id = ? AND id IN ({placeholders})
            """,
            params,
        )
        conn.commit()
        return int(cur.rowcount)
    finally:
        conn.close()


def _is_default_db_connection(conn: sqlite3.Connection) -> bool:
    cur = conn.cursor()
    cur.execute("PRAGMA database_list")
    row = cur.fetchone()
    if row is None:
        return False
    db_path = str(row["file"] if isinstance(row, sqlite3.Row) else row[2])
    if not db_path:
        return False
    try:
        return Path(db_path).resolve() == Path(get_default_db_path()).resolve()
    except OSError:
        return False


def _migrate_legacy_user_databases(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("SELECT value FROM metadata WHERE key = 'legacy_user_dbs_migrated_at'")
    if cur.fetchone() is not None:
        return

    db_dir = get_database_dir()
    legacy_paths = [
        path
        for path in sorted(db_dir.glob("*.db"))
        if path.name != DEFAULT_DB_FILENAME and path.stat().st_size > 0
    ]
    if not legacy_paths:
        cur.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("legacy_user_dbs_migrated_at", datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return

    migrated_rows = 0
    for legacy_path in legacy_paths:
        profile_name, status = _legacy_profile_from_db_path(str(legacy_path))
        if not profile_name:
            continue

        legacy_conn = None
        try:
            legacy_conn = sqlite3.connect(legacy_path)
            legacy_conn.row_factory = sqlite3.Row
            legacy_cur = legacy_conn.cursor()
            legacy_cur.execute("SELECT * FROM jobs")
            legacy_rows = legacy_cur.fetchall()
        except sqlite3.Error as exc:
            _emit_log(logging.WARNING, "Skipping legacy DB %s: %s", legacy_path, exc)
            continue
        finally:
            if legacy_conn is not None:
                legacy_conn.close()

        profile_id = _get_profile_id(conn, profile_name)
        for row in legacy_rows:
            row_keys = set(row.keys())
            job = {
                "job_title": row["job_title"] if "job_title" in row_keys else "",
                "job_location": row["job_location"] if "job_location" in row_keys else "",
                "job_description": row["job_description"] if "job_description" in row_keys else "",
                "job_url": row["job_url"] if "job_url" in row_keys else "",
                "date": row["date"] if "date" in row_keys else "",
                "type": row["type"] if "type" in row_keys else "",
                "isRemote": bool(row["isRemote"]) if "isRemote" in row_keys else False,
                "salary": row["salary"] if "salary" in row_keys else "",
                "company_name": row["company_name"] if "company_name" in row_keys else "",
                "source": row["source"] if "source" in row_keys else "",
                "LLMComment": row["LLMComment"] if "LLMComment" in row_keys else DEFAULT_LLM_COMMENT,
                "raw_columns": _safe_load_raw_columns(row["raw_columns"]) if "raw_columns" in row_keys else [],
            }
            job_id = _upsert_job(conn, job)
            _insert_or_update_profile_job(
                conn,
                profile_id=profile_id,
                job_id=job_id,
                status=status if status == STATUS_UNWANTED else STATUS_RECOMMENDED,
                llm_comment=job.get("LLMComment"),
            )
            migrated_rows += 1

    cur.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        ("legacy_user_dbs_migrated_at", datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    _emit_log(logging.INFO, "Migrated %d legacy profile job row(s) into shared DB", migrated_rows)
