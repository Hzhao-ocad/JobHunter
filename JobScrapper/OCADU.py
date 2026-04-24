#!/usr/bin/env python3
"""OCADU Taleo scraper.

This module scrapes OCAD University job listings from Taleo and returns
normalized job dictionaries using ``build_job_data``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

try:
	from JobStruct import build_job_data
except Exception:
	import os
	import sys

	root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
	if root not in sys.path:
		sys.path.insert(0, root)
	from JobStruct import build_job_data


BASE_SEARCH_URL = "https://tre.tbe.taleo.net/tre01/ats/careers/v2/searchResults"
DEFAULT_ORG = "OCADU"
DEFAULT_CWS_CANDIDATES = (37, 41, 42, 1)
DEFAULT_HEADERS = {
	"User-Agent": (
		"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
		"AppleWebKit/537.36 (KHTML, like Gecko) "
		"Chrome/123.0.0.0 Safari/537.36"
	),
	"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
	"Accept-Language": "en-CA,en;q=0.9",
}


def _build_search_url(org: str, cws: int) -> str:
	return f"{BASE_SEARCH_URL}?{urlencode({'org': org, 'cws': cws})}"


def _extract_salary(text: str) -> str:
	if not text:
		return ""
	pattern = re.compile(
		r"(\$\s?[\d,]+(?:\.\d+)?(?:\s*(?:to|-|–)\s*\$\s?[\d,]+(?:\.\d+)?)?(?:\s*(?:per\s*(?:annum|year|hour)|/\s*(?:yr|year|hr|hour)))?)",
		re.IGNORECASE,
	)
	match = pattern.search(text)
	return match.group(1).strip() if match else ""


def _extract_mode_of_work(description_text: str) -> str:
	if not description_text:
		return ""

	match = re.search(r"Mode of Work\s*:\s*([^\n\.]+)", description_text, flags=re.IGNORECASE)
	if not match:
		return ""
	return match.group(1).strip()


def _extract_deadline(description_text: str) -> str:
	if not description_text:
		return ""

	match = re.search(
		r"(?:no later than|by)\s+(?:[A-Za-z]+\s+)?([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?\s*,?\s*\d{4})",
		description_text,
		flags=re.IGNORECASE,
	)
	if not match:
		return ""
	return match.group(1).strip().replace("  ", " ")


def _looks_remote(mode_of_work: str, description_text: str) -> bool:
	combined = f"{mode_of_work} {description_text}".lower()
	return any(keyword in combined for keyword in ("remote", "hybrid", "work from home"))


def _sanitize_next_href(href: str) -> str:
	# Taleo occasionally emits an invalid entity in the next-link query string.
	return (href or "").replace("¤tTime", "currentTime")


def _fetch_job_details(session: requests.Session, job_url: str, timeout: int) -> Dict[str, Any]:
	response = session.get(job_url, timeout=timeout)
	response.raise_for_status()

	soup = BeautifulSoup(response.text, "html.parser")

	summary_info: Dict[str, str] = {}
	summary = soup.select_one("div.well.oracletaleocwsv2-job-description")
	if summary:
		for section in summary.select("div.row > div"):
			label = section.select_one("span.small")
			value = section.select_one("strong")
			if not label or not value:
				continue
			key = label.get_text(" ", strip=True).strip().rstrip(":")
			val = value.get_text(" ", strip=True)
			if key and val:
				summary_info[key] = val

	description_block = soup.select_one('div[name="cwsJobDescription"]')
	description_text = description_block.get_text("\n", strip=True) if description_block else ""

	mode_of_work = _extract_mode_of_work(description_text)
	deadline = _extract_deadline(description_text)
	salary = _extract_salary(description_text)

	return {
		"summary": summary_info,
		"description": description_text,
		"mode_of_work": mode_of_work,
		"deadline": deadline,
		"salary": salary,
	}


def scrape_ocadu_jobs(
	org: str = DEFAULT_ORG,
	cws: Optional[int] = None,
	max_pages: int = 10,
	timeout: int = 20,
	fetch_details: bool = True,
) -> List[Dict[str, Any]]:
	"""Scrape OCADU Taleo listings into normalized job dictionaries."""
	session = requests.Session()
	session.headers.update(DEFAULT_HEADERS)

	candidates: List[int] = []
	if cws is not None:
		candidates.append(cws)
	candidates.extend(candidate for candidate in DEFAULT_CWS_CANDIDATES if candidate not in candidates)

	current_url = ""
	current_html = ""
	active_cws: Optional[int] = None

	for candidate in candidates:
		candidate_url = _build_search_url(org, candidate)
		try:
			response = session.get(candidate_url, timeout=timeout)
			response.raise_for_status()
		except requests.RequestException:
			continue

		if "viewRequisition" not in response.text:
			continue

		current_url = response.url or candidate_url
		current_html = response.text
		active_cws = candidate
		break

	if not current_html:
		raise RuntimeError(
			"Could not load OCADU Taleo search results. "
			"The source may be blocking requests or may require a different cws context."
		)

	jobs: List[Dict[str, Any]] = []
	seen_job_urls = set()
	seen_page_urls = {current_url}
	details_cache: Dict[str, Dict[str, Any]] = {}

	page_count = 0
	while current_html and page_count < max_pages:
		page_count += 1
		soup = BeautifulSoup(current_html, "html.parser")
		blocks = soup.select("div.oracletaleocwsv2-accordion-block")

		if not blocks:
			break

		for block in blocks:
			title_link = block.select_one("a.viewJobLink[href]")
			if not title_link:
				continue

			job_url = urljoin(current_url, title_link["href"])
			if job_url in seen_job_urls:
				continue

			seen_job_urls.add(job_url)
			title = title_link.get_text(" ", strip=True)

			head_info = block.select_one("div.oracletaleocwsv2-accordion-head-info")
			meta_values = []
			if head_info:
				meta_values = [
					item.get_text(" ", strip=True)
					for item in head_info.select("div[tabindex]")
					if item.get_text(" ", strip=True)
				]

			job_category = meta_values[0] if len(meta_values) > 0 else ""
			employment_type = meta_values[1] if len(meta_values) > 1 else ""
			department = meta_values[2] if len(meta_values) > 2 else ""

			details: Dict[str, Any] = {
				"summary": {},
				"description": "",
				"mode_of_work": "",
				"deadline": "",
				"salary": "",
			}

			if fetch_details:
				if job_url not in details_cache:
					try:
						details_cache[job_url] = _fetch_job_details(session, job_url, timeout)
					except requests.RequestException:
						details_cache[job_url] = details
				details = details_cache[job_url]

			summary_info = details.get("summary", {}) or {}
			department = summary_info.get("Department", department) or department
			employment_type = summary_info.get("Employment Type", employment_type) or employment_type
			job_code = summary_info.get("Job Code", "")

			description = details.get("description", "")
			mode_of_work = details.get("mode_of_work", "")
			deadline = details.get("deadline", "")
			salary = details.get("salary", "")

			location = "Toronto, ON"
			if mode_of_work:
				location = f"{location} ({mode_of_work})"

			job_data = build_job_data(
				job_title=title,
				company_name="OCAD University",
				job_location=location,
				job_description=description or "N/A",
				job_url=job_url,
				date=deadline or "N/A",
				job_type=employment_type or job_category,
				is_remote=_looks_remote(mode_of_work, description),
				salary=salary,
				source=f"OCADU Taleo (cws={active_cws})" if active_cws is not None else "OCADU Taleo",
				raw_columns=[
					f"job_category: {job_category or 'N/A'}",
					f"employment_type: {employment_type or 'N/A'}",
					f"department: {department or 'N/A'}",
					f"mode_of_work: {mode_of_work or 'N/A'}",
					f"job_code: {job_code or 'N/A'}",
				],
			)
			jobs.append(job_data)

		next_link = soup.select_one("a.jscroll-next[href]")
		if not next_link:
			break

		next_href = _sanitize_next_href(next_link.get("href", ""))
		if not next_href:
			break

		next_url = urljoin(current_url, next_href)
		if next_url in seen_page_urls:
			break
		seen_page_urls.add(next_url)

		try:
			next_response = session.get(next_url, timeout=timeout)
			next_response.raise_for_status()
		except requests.RequestException:
			break

		current_url = next_response.url or next_url
		current_html = next_response.text

	return jobs


def OCADU_Scrape() -> List[Dict[str, Any]]:
	"""Required scraper entrypoint returning normalized OCADU listings."""
	return scrape_ocadu_jobs()


def GetOCADUJobs() -> List[Dict[str, Any]]:
	return OCADU_Scrape()