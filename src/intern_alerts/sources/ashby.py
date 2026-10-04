"""Ashby public job boards."""

from typing import Any

import httpx

from intern_alerts.config import Board
from intern_alerts.models import Posting
from intern_alerts.sources import SourceError, get_json, parse_iso_utc

API_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def parse_ashby(data: dict[str, Any], board: Board) -> list[Posting]:
    postings = []
    for job in data["jobs"]:
        if not job.get("isListed", True):
            continue
        locations = [job["location"]]
        locations += [loc["location"] for loc in job.get("secondaryLocations", [])]
        postings.append(
            Posting(
                source="ashby",
                board_key=board.key,
                job_id=job["id"],
                company=board.name,
                title=job["title"].strip(),
                locations=tuple(loc.strip() for loc in locations),
                url=job["jobUrl"],
                posted_at=parse_iso_utc(job["publishedAt"]),
                employment_type=job.get("employmentType"),
            )
        )
    return postings


def fetch_ashby(client: httpx.Client, board: Board) -> list[Posting]:
    data = get_json(client, API_URL.format(slug=board.slug), board.key)
    try:
        return parse_ashby(data, board)
    except (KeyError, TypeError, ValueError) as e:
        raise SourceError(f"{board.key}: unexpected response format ({e!r})") from e
