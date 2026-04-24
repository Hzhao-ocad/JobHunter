#!/usr/bin/env python3
"""
Simple scraper for the U of T CUPE 3902 opportunities page.
Extracts rows from table id="searchresults" and returns normalized
job dictionaries in the structure: tables -> table -> job_data_dict.

Usage:
  pip install requests beautifulsoup4 lxml
  python ut_jobs_scraper.py
  python ut_jobs_scraper.py <url>
"""

import sys

import requests
from bs4 import BeautifulSoup

from JobStruct import *


def scrape_searchresults(url: str):
    headers = {"User-Agent": "Mozilla/5.0 (compatible)"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    tables = soup.find_all("table", id="searchresults")
    if not tables:
        raise RuntimeError("table with id 'searchresults' not found")

    tables_data = []
    for table in tables:
        rows = []
        tbody = table.find("tbody") or table
        for tr in tbody.find_all("tr"):
            if tr.find("th"):
                continue
            tds = tr.find_all("td")
            if not tds:
                continue

            cells = [td.get_text(" ", strip=True) for td in tds]
            col_1 = cells[0] if len(cells) > 0 else ""
            col_2 = cells[1] if len(cells) > 1 else ""
            col_3 = cells[2] if len(cells) > 2 else ""
            col_4 = cells[3] if len(cells) > 3 else ""

            # Include first detail link when present.
            a = tr.find("a", href=True)
            link = requests.compat.urljoin(url, a["href"]) if a else ""

            joined_text = " | ".join(cells)
            job_data = build_job_data(
                job_title=col_1,
                company_name=col_2,
                job_location=col_3,
                date=col_4,
                job_description="N/A",
                job_url=link,
                job_type="N/A",
                is_remote="N/A",
                salary="N/A",
                raw_columns=cells,
            )

            rows.append(job_data)

        #tables_data.append(rows)

    return rows


def getUoftjobs():
    url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://jobs.utoronto.ca/go/CUPE-3902-%28Unit-3%29-Opportunities/2607317/"
    )
    tables = scrape_searchresults(url)
    return tables
