"""PayPal's public Eightfold PCSx search, with complete-board validation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from math import isfinite
from time import perf_counter
from typing import Any
from urllib.parse import urlencode

import httpx

from intern_alerts.config import Board
from intern_alerts.models import Posting
from intern_alerts.sources import SourceError, get_json

BASE_URL = "https://paypal.eightfold.ai"
PAGE_SIZE = 10
WORKERS = 4
MAX_PAGES = 1000


def _page(client: httpx.Client, board: Board, start: int) -> tuple[int, list[dict]]:
    query = urlencode({
        "domain": "paypal.com", "query": "", "location": "",
        # Timestamp order overlaps across pages of equal-dated postings.
        # Relevance with an empty query was validated against complete scans.
        "start": start, "sort_by": "relevance",
    })
    response = get_json(client, f"{BASE_URL}/api/pcsx/search?{query}", board.key)
    if not isinstance(response, dict) or response.get("status") != 200:
        raise ValueError("invalid API status")
    error = response.get("error")
    if not isinstance(error, dict) or error.get("message") or error.get("body"):
        raise ValueError("API error")
    data = response["data"]
    if data["sortBy"] != "relevance":
        raise ValueError("requested relevance sort was not applied")
    if data["resultsMetaData"]["usedFuzzSearch"] is not False:
        raise ValueError("unexpected fuzzy search")
    count, rows = data["count"], data["positions"]
    if type(count) is not int or not 0 <= count <= PAGE_SIZE * MAX_PAGES:
        raise ValueError("invalid or oversized count")
    if not isinstance(rows, list) or len(rows) != min(PAGE_SIZE, max(0, count - start)):
        raise ValueError("incomplete page")
    return count, rows


def _posting(row: dict[str, Any], board: Board) -> Posting:
    job_id = row["id"]
    if type(job_id) is not int or job_id <= 0:
        raise ValueError("invalid position ID")
    path = f"/careers/job/{job_id}"
    if row["positionUrl"] != path:
        raise ValueError("position URL does not match ID")
    title, locations, timestamp = row["name"], row["locations"], row["postedTs"]
    if not isinstance(title, str) or not title.strip():
        raise ValueError("missing title")
    if not isinstance(locations, list) or not locations or any(
        not isinstance(location, str) or not location.strip() for location in locations
    ):
        raise ValueError("invalid locations")
    if type(timestamp) not in (int, float) or not isfinite(timestamp) or timestamp <= 0:
        raise ValueError("invalid posting timestamp")
    locations = [location.strip() for location in locations]
    if row.get("workLocationOption") == "remote":
        locations = [
            location if "remote" in location.lower() else f"Remote - {location}"
            for location in locations
        ]
    return Posting(
        source="eightfold",
        board_key=board.key,
        job_id=str(job_id),
        company=board.name,
        title=title.strip(),
        locations=tuple(locations),
        url=BASE_URL + path,
        posted_at=datetime.fromtimestamp(timestamp, UTC),
    )


def fetch_eightfold(client: httpx.Client, board: Board) -> list[Posting]:
    """Return all search rows only after every page and final count succeeds.

    Search supplies the full Posting shape; eligibility stays in the shared
    classifier. No detail requests or description-based internship inference.
    """
    if board.slug != "paypal" or board.name != "PayPal":
        raise SourceError(f"{board.key}: only the validated PayPal tenant is supported")
    began = perf_counter()
    try:
        count, first = _page(client, board, 0)
        rows = list(first)
        offsets = range(PAGE_SIZE, count, PAGE_SIZE)
        # Submit at most four pages at once; preserve source order.
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for start in range(0, len(offsets), WORKERS):
                pages = pool.map(
                    lambda offset: _page(client, board, offset),
                    offsets[start:start + WORKERS],
                )
                for page_count, page_rows in pages:
                    if page_count != count:
                        raise ValueError("count changed during pagination")
                    rows.extend(page_rows)
        postings = [_posting(row, board) for row in rows]
        unique_count = len({p.job_id for p in postings})
        if len(postings) != count or unique_count != count:
            raise ValueError(
                f"missing or repeated position IDs: expected {count}, "
                f"received {len(postings)} rows / {unique_count} unique IDs"
            )
        final_count, final_rows = _page(client, board, 0)
        if final_count != count or [r["id"] for r in final_rows] != [r["id"] for r in first]:
            raise ValueError("search changed during scan")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as error:
        raise SourceError(f"{board.key}: invalid Eightfold search ({error})") from error
    print(f"{board.key}: verified {count} search rows in {perf_counter() - began:.2f}s")
    return postings
