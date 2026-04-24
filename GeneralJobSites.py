import csv
from datetime import date, datetime
from typing import Any

from jobspy import scrape_jobs

from JobStruct import build_job_data, parse_job_data


def _format_salary(row: dict[str, Any]) -> str:
    currency = str(row.get("currency", "") or "").strip()
    interval = str(row.get("interval", "") or "").strip()
    min_amount = row.get("min_amount")
    max_amount = row.get("max_amount")

    amount_text = ""
    if min_amount is not None or max_amount is not None:
        min_amount_text = f"{min_amount:,}" if isinstance(min_amount, (int, float)) else str(min_amount)
        max_amount_text = f"{max_amount:,}" if isinstance(max_amount, (int, float)) else str(max_amount)
        currency_prefix = f"{currency} " if currency else ""

        if min_amount and max_amount and min_amount != max_amount:
            amount_text = f"{currency_prefix}{min_amount_text} - {currency_prefix}{max_amount_text}"
        else:
            amount_text = f"{currency_prefix}{min_amount_text or max_amount_text}"

    if amount_text and interval:
        return f"{amount_text} / {interval}"

    salary_source = row.get("salary_source")
    salary_source_text = str(salary_source).strip() if salary_source not in (None, "None") else ""
    return amount_text or salary_source_text or ""


def _parse_remote(row: dict[str, Any]) -> bool:
    if row.get("is_remote"):
        return True

    work_from_home_type = str(row.get("work_from_home_type", "") or "").lower()
    return any(keyword in work_from_home_type for keyword in ["remote", "hybrid", "work from home"])


def _format_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _normalize_job_row(row: dict[str, Any]) -> dict[str, Any]:
    job_url = str(row.get("job_url_direct") or row.get("job_url") or "").strip()
    raw_columns = [f"{key}: {value}" for key, value in row.items() if value not in (None, "")]

    return build_job_data(
        job_title=str(row.get("title") or row.get("job_title") or "").strip(),
        company_name=str(row.get("company") or row.get("company_name") or "").strip(),
        job_location=str(row.get("location") or "").strip(),
        job_description=str(row.get("description") or "").strip(),
        job_url=job_url,
        date=_format_date(row.get("date_posted")),
        job_type=str(row.get("job_type") or "").strip(),
        is_remote=_parse_remote(row),
        salary=_format_salary(row),
        source=str(row.get("site") or "jobspy").strip(),
        raw_columns=raw_columns,
    )




def GetGeneralJobs():

    jobs = scrape_jobs(
    site_name=["indeed", "linkedin", "zip_recruiter", "google"], # "glassdoor", "bayt", "naukri", "bdjobs"
    search_term="Art",
    google_search_term="Art, physical computing, Research Assistant,Unreal Engine, near Toronto, ON since yesterday",
    location="Toronto, ON",
    results_wanted=20,
    hours_old=72,
    country_indeed='Canada',
    linkedin_fetch_description=True,  # gets more info such as description, direct job url (slower)
    # proxies=["208.195.175.46:65095", "208.195.175.45:65095", "localhost"],
)

    job_rows = jobs.to_dict(orient="records") if hasattr(jobs, "to_dict") else list(jobs)
    job_structs = [_normalize_job_row(row) for row in job_rows]

    final_jobs += job_structs

    jobs = scrape_jobs(
        site_name=["indeed", "linkedin", "zip_recruiter", "google"], # "glassdoor", "bayt", "naukri", "bdjobs"
        search_term="Research Assistant",
        google_search_term="Art, physical computing, Research Assistant,Unreal Engine, near Toronto, ON since yesterday",
        location="Toronto, ON",
        results_wanted=20,
        hours_old=72,
        country_indeed='Canada',
        linkedin_fetch_description=True,  # gets more info such as description, direct job url (slower)
        # proxies=["208.195.175.46:65095", "208.195.175.45:65095", "localhost"],
    )

    job_rows = jobs.to_dict(orient="records") if hasattr(jobs, "to_dict") else list(jobs)
    job_structs = [_normalize_job_row(row) for row in job_rows]
    
    final_jobs += job_structs
    
    return final_jobs

