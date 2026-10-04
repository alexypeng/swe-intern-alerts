"""Simplify's internship listings, limited to FAANG+ companies."""

from datetime import UTC, datetime
from typing import Any

import httpx

from intern_alerts.models import Posting
from intern_alerts.sources import SourceError, get_json

BOARD_KEY = "simplify:faang"


def parse_simplify(data: list[dict[str, Any]], faang_plus: frozenset[str]) -> list[Posting]:
    postings = []
    for item in data:
        if not (item["active"] and item["is_visible"]):
            continue
        if item["company_name"].strip().lower() not in faang_plus:
            continue
        postings.append(
            Posting(
                source="simplify",
                board_key=BOARD_KEY,
                job_id=item["id"],
                company=item["company_name"].strip(),
                title=item["title"].strip(),
                locations=tuple(item["locations"]),
                url=item["url"],
                posted_at=datetime.fromtimestamp(item["date_posted"], UTC),
                category=item["category"],
            )
        )
    return postings


def fetch_simplify(client: httpx.Client, url: str, faang_plus: frozenset[str]) -> list[Posting]:
    data = get_json(client, url, BOARD_KEY)
    try:
        return parse_simplify(data, faang_plus)
    except (KeyError, TypeError, ValueError) as e:
        raise SourceError(f"{BOARD_KEY}: unexpected response format ({e!r})") from e
