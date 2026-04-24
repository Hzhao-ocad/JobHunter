"""A small helper to fetch Akimbo listings filtered by `fwp_happening`.

Provides a self-contained function `fetch_akimbo_listings(happening, ...)`
that returns a list of dictionaries extracted from each card element.
"""

from typing import List, Dict, Optional, Any





def fetch_akimbo_listings(happening: Optional[str] = None, sublisting_type: Optional[str] = None, sort: Optional[str] = None, base_url: str = "https://akimbo.ca/listings/", timeout: int = 10) -> List[Dict[str, Optional[str]]]:
	"""Fetch Akimbo listings for a given `fwp_happening` value and return
	normalized job dictionaries produced by `build_job_data` from `JobStruct`.

	This function is self-contained for HTTP/HTML dependencies and will
	raise helpful ImportError messages if `requests` or `beautifulsoup4`
	are missing. It will also attempt to import `build_job_data` from
	`JobStruct.py` (project root) and adjust `sys.path` if needed.
	"""
	try:
		import requests
	except Exception as exc:  # pragma: no cover - clear user-facing error
		raise ImportError("The 'requests' package is required. Install it with: pip install requests") from exc

	try:
		from bs4 import BeautifulSoup
	except Exception as exc:  # pragma: no cover - clear user-facing error
		raise ImportError("The 'beautifulsoup4' package is required. Install it with: pip install beautifulsoup4") from exc

	from urllib.parse import urljoin
	# import build_job_data from JobStruct (try package import then fallback to repo root)
	try:
		from JobStruct import build_job_data
	except Exception:
		import sys, os
		root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
		if root not in sys.path:
			sys.path.insert(0, root)
		from JobStruct import build_job_data

	# build query params (only include provided values)
	params = {}
	if happening:
		params["fwp_happening"] = happening
	if sublisting_type:
		params["fwp_sublisting_type"] = sublisting_type
	if sort:
		params["fwp_sort"] = sort

	resp = requests.get(base_url, params=params or None, timeout=timeout, headers={"User-Agent": "python-requests/akimbo-scraper/1.0"})
	resp.raise_for_status()
	soup = BeautifulSoup(resp.text, "html.parser")

	container = soup.select_one("div.card-columns.col-count-3") or soup.select_one("div.card-columns")
	cards = []
	if container:
		cards = container.select("div.card-masonry-wrapper.col-12.col-sm-6.col-xl-4")

	jobs: List[Dict[str, Optional[str]]] = []
	for index, card in enumerate(cards, start=1):
		# title
		title: Optional[str] = None
		title_tag = card.find(["h1", "h2", "h3", "h4"]) or card.select_one(".card-title, .listing-title")
		if title_tag and title_tag.get_text(strip=True):
			title = title_tag.get_text(strip=True)
		else:
			link_tag = card.find("a", href=True)
			if link_tag:
				title = link_tag.get_text(strip=True) or None

		# url
		url: Optional[str] = None
		link = card.find("a", href=True)
		if link:
			url = urljoin(base_url, link["href"])

		# date/time
		date: Optional[str] = None
		time_tag = card.find("time")
		if time_tag:
			date = time_tag.get_text(strip=True)
		else:
			date_el = card.select_one(".event-date, .date, .listing-date")
			if date_el:
				date = date_el.get_text(strip=True)

		# location
		location: Optional[str] = None
		loc_el = card.select_one(".location, .venue, .event-venue")
		if loc_el:
			location = loc_el.get_text(strip=True)
		else:
			meta = card.select_one(".meta, .card-meta")
			if meta:
				location = meta.get_text(strip=True)

		# company/organizer
		company_name: Optional[str] = None
		company_el = card.select_one(".organizer, .company, .listing-organization, .event-organizer, .publisher")
		if company_el:
			company_name = company_el.get_text(strip=True)

		# description / excerpt
		description: Optional[str] = None
		desc_el = card.select_one(".card-description, .excerpt, .listing-excerpt, p")
		if desc_el:
			description = desc_el.get_text(strip=True)

		# detect remote heuristically
		_text = " ".join([str(x or "") for x in (title, location, description, company_name)])
		lower_text = _text.lower()
		is_remote = any(k in lower_text for k in ("remote", "hybrid", "work from home"))

		# build normalized job dict
		job = build_job_data(
			job_title=title or "Akimbo Event",
			job_location=location or "Toronto",
			job_description=description or "",
			job_url=url or "Akimbo Listing",
			date=date or "N/A",
			job_type="N/A",
			is_remote=is_remote,
			salary="N/A",
			company_name=company_name or "",
			source="Akimbo",
			raw_columns=[str(card)],
		)
		# attach index for callers that want it
		job["index"] = index
		jobs.append(job)

	return jobs


def dedupe_calls(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
	"""Remove duplicate job entries while preserving order.

	Deduplication priority:
	- If `job_url` looks like a real URL (starts with http/https), use a normalized
	  URL as the unique key.
	- Otherwise fall back to a tuple of (title, company_name, job_location) lowercased.
	"""
	def _key_for(job: Dict[str, Any]):
		url = (job.get("job_url") or "").strip()
		if url and url.lower().startswith("http"):
			return ("url", url.rstrip("/").lower())
		return (
			"triplet",
			(job.get("job_title") or "").strip().lower(),
			(job.get("company_name") or "").strip().lower(),
			(job.get("job_location") or "").strip().lower(),
		)

	seen = set()
	out: List[Dict[str, Any]] = []
	for j in jobs:
		k = _key_for(j)
		if k in seen:
			continue
		seen.add(k)
		out.append(j)
	return out

def GetAkimboJobs():
	call_1 = fetch_akimbo_listings(happening = "toronto", sublisting_type = "calls")
	call_2 = fetch_akimbo_listings(happening = "toronto", sublisting_type = "calls", sort = "last_chance")


	call_3 = fetch_akimbo_listings(happening = "toronto", sublisting_type = "learning")
	call_4 = fetch_akimbo_listings(happening = "toronto", sublisting_type = "learning", sort = "last_chance")


	call_5 = fetch_akimbo_listings(happening = "toronto", sublisting_type = "jobs")
	call_6 = fetch_akimbo_listings(happening = "toronto", sublisting_type = "jobs", sort = "last_chance")



	calls = dedupe_calls(call_1 + call_2 + call_3 + call_4 + call_5 + call_6)
	return calls