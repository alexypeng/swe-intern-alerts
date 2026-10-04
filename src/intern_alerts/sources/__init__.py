"""Fetchers that turn each job source's API response into Postings."""

from datetime import UTC, datetime
from typing import Any

import httpx

TIMEOUT_SECONDS = 20


class SourceError(Exception):
    """A board or feed could not be fetched or parsed. Its postings should not be trusted."""


def new_client() -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": "intern-alerts"},
    )


def get_json(client: httpx.Client, url: str, label: str) -> Any:
    try:
        response = client.get(url)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as e:
        raise SourceError(f"{label}: {e}") from e


def parse_iso_utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)
