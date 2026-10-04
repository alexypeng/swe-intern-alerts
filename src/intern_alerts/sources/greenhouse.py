"""Greenhouse public job boards."""

from typing import Any

import httpx

from intern_alerts.config import Board
from intern_alerts.models import Posting
from intern_alerts.sources import SourceError, get_json, parse_iso_utc

API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def parse_greenhouse(data: dict[str, Any], board: Board) -> list[Posting]:
    return [
        Posting(
            source="greenhouse",
            board_key=board.key,
            job_id=str(job["id"]),
            company=board.name,
            title=job["title"].strip(),
            # One free-text string, e.g. "New York, Seattle". Commas are ambiguous
            # ("Seattle, WA"), so classification parses it rather than splitting here.
            locations=(job["location"]["name"].strip(),),
            url=job["absolute_url"],
            posted_at=parse_iso_utc(job.get("first_published") or job["updated_at"]),
        )
        for job in data["jobs"]
    ]


def fetch_greenhouse(client: httpx.Client, board: Board) -> list[Posting]:
    data = get_json(client, API_URL.format(slug=board.slug), board.key)
    try:
        return parse_greenhouse(data, board)
    except (KeyError, TypeError, ValueError) as e:
        raise SourceError(f"{board.key}: unexpected response format ({e!r})") from e
