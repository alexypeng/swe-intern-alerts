"""Lever public job boards."""

from datetime import UTC, datetime
from typing import Any

import httpx

from intern_alerts.config import Board
from intern_alerts.models import Posting
from intern_alerts.sources import SourceError, get_json

API_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"


def parse_lever(data: list[dict[str, Any]], board: Board) -> list[Posting]:
    postings = []
    for job in data:
        categories = job.get("categories") or {}
        locations = categories.get("allLocations") or [categories.get("location") or ""]
        if job.get("workplaceType") == "remote":
            # Feeds the region rules: "Remote - <place in a listed region>" goes under Remote.
            locations = [loc if "remote" in loc.lower() else f"Remote - {loc}" for loc in locations]
        postings.append(
            Posting(
                source="lever",
                board_key=board.key,
                job_id=job["id"],
                company=board.name,
                title=job["text"].strip(),
                locations=tuple(loc.strip() for loc in locations),
                url=job["hostedUrl"],
                posted_at=datetime.fromtimestamp(job["createdAt"] / 1000, UTC),
                # Free text set per company: "Internship", "Intern", "Full-time", or missing.
                employment_type=categories.get("commitment"),
            )
        )
    return postings


def fetch_lever(client: httpx.Client, board: Board) -> list[Posting]:
    data = get_json(client, API_URL.format(slug=board.slug), board.key)
    try:
        return parse_lever(data, board)
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise SourceError(f"{board.key}: unexpected response format ({e!r})") from e
