#!/usr/bin/env python3
"""Streamlit status viewer for the JobHunter main pipeline."""

from __future__ import annotations

import json
import subprocess
import sys
import sqlite3
import time
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from jobhunter.config.profiles import normalize_name_need
from jobhunter.config.settings import DEFAULT_CONFIG_PATH, DEFAULT_RUN_TIMES
from jobhunter.jobs.formatting import parse_job_data
from jobhunter.llm.response_parser import parse_json_to_job_reason_pairs
from jobhunter.paths import LOG_DIR, PROJECT_ROOT
from jobhunter.pipeline.scheduler import get_next_run, parse_run_times
from jobhunter.pipeline.status_store import STATUS_PATH, append_event, read_status, update_status
from jobhunter.storage.database import connect_db
from jobhunter.storage.schema import create_jobs_table


ROOT = PROJECT_ROOT


st.set_page_config(
    page_title="JobHunter Status",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        :root {
            --ink: #18231f;
            --muted: #53625b;
            --line: #d9e1dd;
            --surface: #ffffff;
            --soft: #f4f7f5;
            --accent: #0b6b5d;
            --warn: #a85722;
            --bad: #a82f38;
        }
        .stApp { background: #f7f9f8; color: var(--ink); }
        .block-container { max-width: 1360px; padding-top: 1.4rem; }
        h1, h2, h3 { color: var(--ink) !important; letter-spacing: 0; }
        [data-testid="stSidebar"] { background: #eef3f0; border-right: 1px solid var(--line); }
        .jh-header {
            border-bottom: 1px solid var(--line);
            padding-bottom: .9rem;
            margin-bottom: 1rem;
        }
        .jh-title { font-size: 2rem; font-weight: 760; margin: 0; }
        .jh-subtitle { color: var(--muted); margin: .25rem 0 0; }
        .metric-box {
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: .8rem .9rem;
            min-height: 92px;
        }
        .metric-label {
            color: var(--muted);
            font-size: .76rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: .05em;
        }
        .metric-value {
            color: var(--ink);
            font-size: 1.38rem;
            font-weight: 760;
            margin-top: .2rem;
            overflow-wrap: anywhere;
        }
        .metric-note { color: var(--muted); font-size: .82rem; margin-top: .25rem; }
        .status-pill {
            display: inline-block;
            border: 1px solid var(--line);
            border-radius: 999px;
            padding: .18rem .55rem;
            background: var(--soft);
            color: var(--ink);
            font-size: .82rem;
        }
        .status-new { color: var(--accent); font-weight: 700; }
        .status-recommended { color: #2f5da8; font-weight: 700; }
        .status-unwanted { color: var(--warn); font-weight: 700; }
        .mini-muted { color: var(--muted); font-size: .86rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def clean(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "null"}:
        return fallback
    return text


def render_metric(label: str, value: Any, note: str = "") -> None:
    st.markdown(
        f"""
        <div class="metric-box">
            <div class="metric-label">{escape(label)}</div>
            <div class="metric-value">{escape(str(value))}</div>
            <div class="metric-note">{escape(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_config_users(config: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    return normalize_name_need(config.get("nameNeed", {}))


def load_push_targets(config: Dict[str, Any]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for target in config.get("targets", []) or []:
        if not isinstance(target, dict):
            continue
        rows.append(
            {
                "profile_name": clean(target.get("user_db_name")),
                "channel_id": clean(target.get("channel_id")),
                "role_ids": ", ".join(str(x) for x in target.get("role_ids", []) or []),
                "user_ids": ", ".join(str(x) for x in target.get("user_ids", []) or []),
            }
        )
    return pd.DataFrame(rows)


@st.cache_data(ttl=3)
def load_status_cached() -> Dict[str, Any]:
    return read_status()


@st.cache_data(ttl=5)
def load_profiles() -> pd.DataFrame:
    conn = connect_db()
    try:
        create_jobs_table(conn)
        rows = conn.execute(
            """
            SELECT
                p.id,
                p.name,
                p.discord_user_id,
                p.need,
                p.created_at,
                p.updated_at,
                COUNT(pj.id) AS total_jobs,
                SUM(CASE WHEN pj.status = 'new' THEN 1 ELSE 0 END) AS new_jobs,
                SUM(CASE WHEN pj.status = 'recommended' THEN 1 ELSE 0 END) AS pushed_jobs,
                SUM(CASE WHEN pj.status = 'unwanted' THEN 1 ELSE 0 END) AS unwanted_jobs
            FROM profiles p
            LEFT JOIN profile_jobs pj ON pj.profile_id = p.id
            GROUP BY p.id
            ORDER BY LOWER(p.name)
            """
        ).fetchall()
        return pd.DataFrame([dict(row) for row in rows])
    finally:
        conn.close()


@st.cache_data(ttl=5)
def load_profile_jobs() -> pd.DataFrame:
    conn = connect_db()
    try:
        create_jobs_table(conn)
        rows = conn.execute(
            """
            SELECT
                pj.id AS profile_job_id,
                j.id AS job_id,
                p.name AS profile_name,
                pj.status,
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
                pj.LLMComment,
                j.raw_columns,
                pj.created_at,
                j.created_at AS job_created_at,
                pj.updated_at,
                pj.pushed_at,
                j.dedupe_key
            FROM profile_jobs pj
            JOIN profiles p ON p.id = pj.profile_id
            JOIN jobs j ON j.id = pj.job_id
            ORDER BY pj.created_at DESC, pj.id DESC
            """
        ).fetchall()
        return pd.DataFrame([dict(row) for row in rows])
    finally:
        conn.close()


@st.cache_data(ttl=5)
def load_status_counts() -> pd.DataFrame:
    conn = connect_db()
    try:
        create_jobs_table(conn)
        rows = conn.execute(
            """
            SELECT p.name AS profile_name, pj.status, COUNT(*) AS count
            FROM profile_jobs pj
            JOIN profiles p ON p.id = pj.profile_id
            GROUP BY p.name, pj.status
            ORDER BY LOWER(p.name), pj.status
            """
        ).fetchall()
        return pd.DataFrame([dict(row) for row in rows])
    finally:
        conn.close()


def read_jsonl(path: Path, limit: int | None = None) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    if limit:
        lines = lines[-limit:]
    for line in lines:
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"raw": line})
    return rows


def list_runs() -> List[Path]:
    if not LOG_DIR.exists():
        return []
    return sorted([p for p in LOG_DIR.iterdir() if p.is_dir() and p.name.startswith("run_")], reverse=True)


def extract_llm_jobs(message_text: str) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    current_index: int | None = None
    current_lines: List[str] = []
    for line in message_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Job Index ") and stripped.endswith(":"):
            if current_index is not None:
                chunks.append({"job_index": current_index, "job_text": "\n".join(current_lines).strip()})
            try:
                current_index = int(stripped[len("Job Index ") : -1])
            except ValueError:
                current_index = None
            current_lines = []
        elif current_index is not None:
            current_lines.append(line)
    if current_index is not None:
        chunks.append({"job_index": current_index, "job_text": "\n".join(current_lines).strip()})
    return chunks


def flatten_llm_records(records: List[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for record in records:
        user_name = clean(record.get("user_name"))
        batch_index = record.get("batch_index")
        response_content = clean(record.get("response_content"))
        try:
            recommended_pairs = parse_json_to_job_reason_pairs(response_content)
        except Exception:
            recommended_pairs = []
        reason_by_index = {}
        for job_idx, reason in recommended_pairs:
            if isinstance(job_idx, str) and job_idx.isdigit():
                job_idx = int(job_idx)
            if isinstance(job_idx, int):
                reason_by_index[job_idx] = clean(reason, "Recommended by LLM")

        messages = record.get("messages") or []
        user_message = ""
        if messages and isinstance(messages, list):
            for message in messages:
                if isinstance(message, dict) and message.get("role") == "user":
                    user_message = clean(message.get("content"))
                    break

        for job in extract_llm_jobs(user_message):
            job_index = job["job_index"]
            rows.append(
                {
                    "user_name": user_name,
                    "batch_index": batch_index,
                    "job_index": job_index,
                    "recommended": job_index in reason_by_index,
                    "comment": reason_by_index.get(job_index, "Not recommended by LLM"),
                    "job_text": job["job_text"],
                    "timestamp_utc": record.get("timestamp_utc"),
                    "model": record.get("model"),
                    "provider": record.get("provider"),
                }
            )
    return pd.DataFrame(rows)


def flatten_final_records(records: List[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for record in records:
        for verdict, key in [("recommended", "potential_jobs"), ("unwanted", "unwanted_jobs")]:
            for job in record.get(key, []) or []:
                rows.append(
                    {
                        "user_name": record.get("user_name"),
                        "verdict": verdict,
                        "job_title": job.get("job_title"),
                        "company_name": job.get("company_name"),
                        "job_location": job.get("job_location"),
                        "source": job.get("source"),
                        "LLMComment": job.get("LLMComment"),
                        "job_url": job.get("job_url"),
                        "timestamp_utc": record.get("timestamp_utc"),
                    }
                )
    return pd.DataFrame(rows)


def build_filter_prompt(user_need: str) -> str:
    return (
        "you are a information filtering assistant, a list of job listing will be provided,\n"
        "you will filter the job listing and recommend all relevant jobs to the user based on the user profile and how relevant the job is,\n"
        f"User profile: {user_need}\n"
        "Return your answer strictly in JSON with the following schema, job_index is the index of the job listing in the provided list, and Reasoning is your reasoning for recommending this job to the user.\n"
        "If there are no relevant jobs, return an empty list:\n"
        '[{"Job": job_index, "Reasoning": "..." }]\n'
    )


def run_temp_filter(user_need: str, jobs: List[Dict[str, Any]]) -> pd.DataFrame:
    from jobhunter.llm import client as LLMLayer

    user_query = ""
    for idx, job in enumerate(jobs):
        user_query += f"\nJob Index {idx}:\n{parse_job_data(job)}\n"
    client = LLMLayer.LLMClient()
    response = client.chat(
        user_input=user_query,
        system_prompt=build_filter_prompt(user_need),
        _log_user_name="TEMP_TEST_ONLY",
        _diagnostic_log=False,
    )
    content = client.get_response_content(response)
    try:
        pairs = parse_json_to_job_reason_pairs(content)
    except Exception as exc:
        return pd.DataFrame([{"error": str(exc), "raw_response": content}])

    reason_by_index: Dict[int, str] = {}
    for job_idx, reason in pairs:
        if isinstance(job_idx, str) and job_idx.isdigit():
            job_idx = int(job_idx)
        if isinstance(job_idx, int):
            reason_by_index[job_idx] = clean(reason, "Recommended by LLM")

    rows = []
    for idx, job in enumerate(jobs):
        rows.append(
            {
                "recommended": idx in reason_by_index,
                "comment": reason_by_index.get(idx, "Not recommended by LLM"),
                "job_title": job.get("job_title"),
                "company_name": job.get("company_name"),
                "job_location": job.get("job_location"),
                "source": job.get("source"),
                "status_now": job.get("status"),
                "profile_now": job.get("profile_name"),
                "job_url": job.get("job_url"),
            }
        )
    return pd.DataFrame(rows)


def launch_manual_scrape(config_path: Path) -> tuple[bool, str]:
    current_status = read_status()
    if clean(current_status.get("state")).lower() in {"running", "queued"}:
        return False, "A scrape is already running."

    command = (
        "from jobhunter.pipeline.runner import _configure_logging, run_pipeline_once; "
        "from pathlib import Path; "
        "_configure_logging('INFO'); "
        f"run_pipeline_once(Path({str(config_path)!r}))"
    )
    launcher_log_path = LOG_DIR / "manual_scrape_launcher.log"
    launcher_log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(launcher_log_path, "a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", command],
            cwd=str(ROOT),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        log_fh.close()
        update_status(state="error", phase="manual_scrape_launch_failed", last_error=str(exc))
        append_event("manual_scrape_launch_failed", error=str(exc))
        return False, f"Failed to start scrape: {exc}"
    finally:
        try:
            log_fh.close()
        except OSError:
            pass

    update_status(
        state="queued",
        phase="manual_scrape_requested",
        manual_scrape_pid=process.pid,
        last_manual_scrape_requested_at=datetime.now().isoformat(),
        config_path=str(config_path),
        last_error="",
    )
    append_event("manual_scrape_requested", pid=process.pid, config_path=str(config_path))
    return True, f"Started scrape process {process.pid}."


st.sidebar.markdown("### Viewer")
auto_refresh = st.sidebar.toggle("Auto refresh", value=False)
if st.sidebar.button("Refresh now", width="stretch"):
    st.cache_data.clear()
    st.rerun()

config_path = Path(st.sidebar.text_input("Config path", value=str(DEFAULT_CONFIG_PATH)))
run_times_text = st.sidebar.text_input("Run times", value=DEFAULT_RUN_TIMES)

config = load_config(config_path)
config_users = load_config_users(config)
push_targets_df = load_push_targets(config)
status = load_status_cached()

manual_scrape_disabled = clean(status.get("state")).lower() in {"running", "queued"}
if st.sidebar.button("Start scrape now", type="primary", width="stretch", disabled=manual_scrape_disabled):
    started, message = launch_manual_scrape(config_path)
    if started:
        st.sidebar.success(message)
    else:
        st.sidebar.warning(message)
    st.cache_data.clear()
    time.sleep(1)
    st.rerun()
if manual_scrape_disabled:
    st.sidebar.caption("Scrape controls are disabled while the pipeline is running.")

profiles_df = load_profiles()
jobs_df = load_profile_jobs()
counts_df = load_status_counts()
runs = list_runs()

try:
    next_from_input = get_next_run(datetime.now(), parse_run_times(run_times_text)).strftime("%Y-%m-%d %H:%M:%S")
except Exception as exc:
    next_from_input = f"Invalid run times: {exc}"

next_from_status = clean(status.get("next_run_at"))
current_state = clean(status.get("state"), "unknown")
current_phase = clean(status.get("phase"), "unknown")

st.markdown(
    """
    <div class="jh-header">
        <h1 class="jh-title">JobHunter Status Viewer</h1>
        <p class="jh-subtitle">Live pipeline state, scheduler timing, LLM filtering traces, profile/job database views, and temporary prompt testing.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

metric_cols = st.columns(5)
with metric_cols[0]:
    render_metric("Pipeline", current_state, current_phase)
with metric_cols[1]:
    render_metric("Next Scheduled", next_from_status or next_from_input, "status file first, input fallback")
with metric_cols[2]:
    render_metric("Profiles", len(profiles_df), f"{len(config_users)} in config")
with metric_cols[3]:
    render_metric("Profile Jobs", len(jobs_df), "all profile/status rows")
with metric_cols[4]:
    latest_run = runs[0].name.replace("run_", "") if runs else "none"
    render_metric("Latest Run", latest_run, clean(status.get("updated_at_utc")))

progress_scrape_done = len(status.get("scrape_sources_done") or [])
progress_scrape_total = int(status.get("scrape_sources_total") or 5)
scrape_ratio = min(1.0, progress_scrape_done / max(1, progress_scrape_total))
llm_done = int(status.get("llm_batches_done") or 0)
llm_total = int(status.get("llm_batches_total") or 0)
write_done = int(status.get("db_writes_done") or 0)
write_total = int(status.get("db_writes_total") or 0)

with st.expander("Current Run Progress", expanded=True):
    p1, p2, p3 = st.columns(3)
    with p1:
        st.caption(f"Scrapers: {progress_scrape_done}/{progress_scrape_total}")
        st.progress(scrape_ratio)
        st.write(clean(status.get("current_source"), "No active scraper"))
    with p2:
        st.caption(f"LLM batches: {llm_done}/{llm_total}")
        st.progress(min(1.0, llm_done / max(1, llm_total)))
        st.write(f"{clean(status.get('current_user'), 'No active user')} batch {clean(status.get('current_batch'), '0')}")
    with p3:
        st.caption(f"Database writes: {write_done}/{write_total}")
        st.progress(min(1.0, write_done / max(1, write_total)))
        st.write(clean(status.get("last_error"), "No last error"))

main_tab, db_tab, llm_tab, users_tab, scratch_tab, raw_tab = st.tabs(
    ["Overview", "Database", "LLM Trace", "Users", "Temporary Filter", "Raw Logs"]
)

with main_tab:
    c1, c2 = st.columns([1.1, 1])
    with c1:
        st.subheader("Recent Events")
        events = pd.DataFrame(status.get("events") or [])
        if events.empty:
            st.info(f"No status events yet. Status file: {STATUS_PATH}")
        else:
            st.dataframe(events.iloc[::-1], width="stretch", hide_index=True, height=330)
    with c2:
        st.subheader("Status Counts")
        if counts_df.empty:
            st.info("No profile job status rows yet.")
        else:
            pivot = counts_df.pivot_table(index="profile_name", columns="status", values="count", fill_value=0)
            st.dataframe(pivot, width="stretch")
        st.subheader("Discord Push Targets")
        if push_targets_df.empty:
            st.info("No target mapping found in config.")
        else:
            st.dataframe(push_targets_df, width="stretch", hide_index=True)

with db_tab:
    if jobs_df.empty:
        st.info("No jobs in the shared database yet.")
    else:
        profiles = sorted([x for x in jobs_df["profile_name"].dropna().unique()])
        statuses = sorted([x for x in jobs_df["status"].dropna().unique()])
        sources = sorted([x for x in jobs_df["source"].dropna().unique()])

        f1, f2, f3, f4 = st.columns([1, 1, 1, 1.2])
        selected_profiles = f1.multiselect("Profiles", profiles, default=profiles)
        selected_statuses = f2.multiselect("Status", statuses, default=statuses)
        selected_sources = f3.multiselect("Sources", sources, default=sources)
        keyword = f4.text_input("Search", placeholder="title, company, comment, location")

        filtered = jobs_df.copy()
        if selected_profiles:
            filtered = filtered[filtered["profile_name"].isin(selected_profiles)]
        if selected_statuses:
            filtered = filtered[filtered["status"].isin(selected_statuses)]
        if selected_sources:
            filtered = filtered[filtered["source"].isin(selected_sources)]
        if keyword:
            cols = [c for c in ["job_title", "company_name", "job_location", "LLMComment", "job_description"] if c in filtered.columns]
            mask = pd.Series(False, index=filtered.index)
            for col in cols:
                mask = mask | filtered[col].astype(str).str.contains(keyword, case=False, na=False)
            filtered = filtered[mask]

        display_cols = [
            "profile_name",
            "status",
            "pushed_at",
            "job_title",
            "company_name",
            "job_location",
            "source",
            "LLMComment",
            "job_url",
            "created_at",
            "updated_at",
        ]
        existing = [c for c in display_cols if c in filtered.columns]
        st.dataframe(filtered[existing], width="stretch", hide_index=True, height=520)

with llm_tab:
    if not runs:
        st.info("No diagnostic run folders found.")
    else:
        selected_run = st.selectbox("Run", runs, format_func=lambda p: p.name)
        llm_records = read_jsonl(selected_run / "llm_chat_history.jsonl")
        final_records = read_jsonl(selected_run / "final_results.jsonl")
        scrape_records = read_jsonl(selected_run / "job_search_results.jsonl")

        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Scrape Events", len(scrape_records))
        sc2.metric("LLM Batches", len(llm_records))
        sc3.metric("Final User Results", len(final_records))

        trace_df = flatten_llm_records(llm_records)
        final_df = flatten_final_records(final_records)

        trace_tab, final_tab = st.tabs(["Per Job LLM Comments", "Final Recommended vs Unwanted"])
        with trace_tab:
            if trace_df.empty:
                st.info("This run has no LLM chat history.")
            else:
                users = sorted(trace_df["user_name"].dropna().unique())
                selected_user = st.selectbox("Trace user", users)
                user_trace = trace_df[trace_df["user_name"] == selected_user]
                st.dataframe(
                    user_trace[
                        [
                            "batch_index",
                            "job_index",
                            "recommended",
                            "comment",
                            "job_text",
                            "timestamp_utc",
                            "model",
                            "provider",
                        ]
                    ],
                    width="stretch",
                    hide_index=True,
                    height=560,
                )
        with final_tab:
            if final_df.empty:
                st.info("This run has no final result file.")
            else:
                st.dataframe(final_df, width="stretch", hide_index=True, height=560)

with users_tab:
    if profiles_df.empty:
        st.info("No profiles found.")
    else:
        st.dataframe(profiles_df, width="stretch", hide_index=True)
        selected_profile = st.selectbox("Inspect profile", profiles_df["name"].tolist())
        profile_jobs = jobs_df[jobs_df["profile_name"] == selected_profile].copy() if not jobs_df.empty else pd.DataFrame()
        profile_config_need = ""
        for entry in config_users.values():
            if entry.get("name") == selected_profile:
                profile_config_need = entry.get("need", "")
                break
        db_need = clean(profiles_df.loc[profiles_df["name"] == selected_profile, "need"].iloc[0])
        st.text_area("Current need prompt", value=db_need or profile_config_need, height=140, disabled=True)

        if profile_jobs.empty:
            st.info("This profile has no job rows.")
        else:
            recommended = profile_jobs[profile_jobs["status"].isin(["new", "recommended"])]
            unwanted = profile_jobs[profile_jobs["status"] == "unwanted"]
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("Recommended / Pending")
                st.dataframe(
                    recommended[["status", "job_title", "company_name", "source", "LLMComment", "pushed_at"]],
                    width="stretch",
                    hide_index=True,
                    height=420,
                )
            with c2:
                st.subheader("Unwanted")
                st.dataframe(
                    unwanted[["status", "job_title", "company_name", "source", "LLMComment"]],
                    width="stretch",
                    hide_index=True,
                    height=420,
                )

with scratch_tab:
    st.info("Temporary test only: runs the LLM against selected jobs and does not write to SQLite or diagnostic logs.")
    if jobs_df.empty:
        st.warning("Load jobs into the database first, then rerun a temporary filter here.")
    else:
        existing_profile_names = [entry["name"] for entry in config_users.values()]
        if not existing_profile_names and not profiles_df.empty:
            existing_profile_names = profiles_df["name"].tolist()
        base_user = st.selectbox("Start from existing user prompt", existing_profile_names or [""])
        base_need = ""
        for entry in config_users.values():
            if entry.get("name") == base_user:
                base_need = entry.get("need", "")
                break
        if not base_need and not profiles_df.empty and base_user in profiles_df["name"].values:
            base_need = clean(profiles_df.loc[profiles_df["name"] == base_user, "need"].iloc[0])
        temp_need = st.text_area("Temporary user need", value=base_need, height=180)

        candidate_pool = jobs_df.drop_duplicates(subset=["job_id"]).copy()
        pool_sources = sorted([x for x in candidate_pool["source"].dropna().unique()])
        source_pick = st.multiselect("Limit jobs by source", pool_sources, default=pool_sources[: min(4, len(pool_sources))])
        if source_pick:
            candidate_pool = candidate_pool[candidate_pool["source"].isin(source_pick)]
        keyword = st.text_input("Limit jobs by keyword", placeholder="optional")
        if keyword:
            cols = [c for c in ["job_title", "company_name", "job_location", "job_description"] if c in candidate_pool.columns]
            mask = pd.Series(False, index=candidate_pool.index)
            for col in cols:
                mask = mask | candidate_pool[col].astype(str).str.contains(keyword, case=False, na=False)
            candidate_pool = candidate_pool[mask]

        candidate_pool = candidate_pool.head(80)
        option_map = {
            int(row["job_id"]): f"{clean(row.get('job_title'), 'Untitled')} | {clean(row.get('company_name'), 'Unknown')} | {clean(row.get('source'))}"
            for _, row in candidate_pool.iterrows()
            if pd.notna(row.get("job_id"))
        }
        selected_job_ids = st.multiselect(
            "Jobs to test",
            options=list(option_map.keys()),
            default=list(option_map.keys())[:10],
            format_func=lambda key: option_map.get(key, str(key)),
        )
        selected_jobs = candidate_pool[candidate_pool["job_id"].isin(selected_job_ids)].to_dict("records")

        if st.button("Run temporary filter", type="primary", disabled=not temp_need.strip() or not selected_jobs):
            with st.spinner("Filtering selected jobs with the temporary prompt..."):
                result_df = run_temp_filter(temp_need, selected_jobs)
            st.dataframe(result_df, width="stretch", hide_index=True, height=520)

with raw_tab:
    st.subheader("Status JSON")
    st.json(status)
    if runs:
        selected_raw_run = st.selectbox("Raw run folder", runs, format_func=lambda p: p.name, key="raw_run")
        summary_path = selected_raw_run / "run_summary.log"
        st.text_area(
            "Run summary",
            value=summary_path.read_text(encoding="utf-8") if summary_path.exists() else "",
            height=260,
        )

if auto_refresh:
    time.sleep(5)
    st.rerun()
