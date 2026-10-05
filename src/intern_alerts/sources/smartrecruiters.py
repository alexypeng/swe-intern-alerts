"""SmartRecruiters public job boards. The API returns at most 100 postings per page."""

from typing import Any

import httpx

from intern_alerts.config import Board
from intern_alerts.models import Posting
from intern_alerts.sources import SourceError, get_json, parse_iso_utc

API_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit={limit}&offset={offset}"
JOB_URL = "https://jobs.smartrecruiters.com/{slug}/{id}"
PAGE_SIZE = 100
MAX_PAGES = 50


def parse_smartrecruiters(items: list[dict[str, Any]], board: Board) -> list[Posting]:
    postings = []
    for job in items:
        location = job.get("location") or {}
        place = location.get("fullLocation") or ""
        if location.get("remote"):
            place = f"Remote - {place}"
        postings.append(
            Posting(
                source="smartrecruiters",
                board_key=board.key,
                job_id=str(job["id"]),
                company=board.name,
                title=job["name"].strip(),
                locations=(place.strip(),),
                url=JOB_URL.format(slug=board.slug, id=job["id"]),
                posted_at=parse_iso_utc(job["releasedDate"]),
                employment_type=(job.get("typeOfEmployment") or {}).get("label"),
            )
        )
    return postings


def fetch_smartrecruiters(client: httpx.Client, board: Board) -> list[Posting]:
    items: list[dict[str, Any]] = []
    try:
        for page in range(MAX_PAGES):
            url = API_URL.format(slug=board.slug, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
            data = get_json(client, url, board.key)
            items += data["content"]
            if not data["content"] or len(items) >= data["totalFound"]:
                break
        else:
            print(f"::warning::{board.key}: stopped after {MAX_PAGES} pages ({len(items)} postings)")
        return parse_smartrecruiters(items, board)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise SourceError(f"{board.key}: unexpected response format ({e!r})") from e
