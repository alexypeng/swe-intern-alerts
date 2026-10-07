"""Workday CXS boards: validated native filters, complete scans, and job details."""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time
from time import perf_counter, sleep
from typing import Any
from urllib.parse import urlsplit

import httpx

from intern_alerts.classify import is_intern_title, is_undergrad_title
from intern_alerts.config import Board
from intern_alerts.models import Posting
from intern_alerts.sources import SourceError
from intern_alerts.sources.workday_education import required_degrees

PAGE_SIZE = 20
# NVIDIA repeats results beyond this window. Refuse potentially capped boards.
RESULT_WINDOW = 2000
DETAIL_RETRY_STATUSES = {502, 503, 504}
DETAIL_RETRY_DELAY_SECONDS = 0.5


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing or invalid required text")
    return value.strip()


def _detail(client: httpx.Client, url: str, board: Board) -> Posting:
    """Retry transient reads once inside the existing detail worker."""
    for attempt in range(2):
        try:
            response = client.get(url)
            response.raise_for_status()
        except (httpx.TransportError, httpx.HTTPStatusError) as error:
            if (attempt or isinstance(error, httpx.HTTPStatusError)
                    and error.response.status_code not in DETAIL_RETRY_STATUSES):
                raise
            print(f"{board.key}: transient detail failure; retrying once: {url}")
            sleep(DETAIL_RETRY_DELAY_SECONDS)
        else:
            # JSON/schema/eligibility failures are not transient read errors.
            return parse_workday(response.json(), board)


def parse_workday(data: dict[str, Any], board: Board) -> Posting:
    info = data["jobPostingInfo"]
    if info.get("posted") is False or info.get("canApply") is False:
        raise ValueError("job became unavailable during fetch; retry board")
    url = _text(info["externalUrl"])
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != board.host or "/job/" not in parts.path:
        raise ValueError("invalid application URL")
    published = _text(info["startDate"])
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published):
        raise ValueError("expected date-only startDate")
    additional = info.get("additionalLocations")
    if additional is None:
        additional = []
    if not isinstance(additional, list):
        raise ValueError("invalid additionalLocations")
    locations = [_text(info["location"]), *(_text(value) for value in additional)]
    description = info.get("jobDescription", "")
    if board.partition_facet or board.filter_facet:
        description = _text(description)  # Filtered/partitioned eligibility must be inspectable.
    return Posting(
        source="workday", board_key=board.key, job_id=_text(info["jobReqId"]),
        company=board.name, title=_text(info["title"]),
        locations=tuple(dict.fromkeys(locations)), url=url,
        # Validated against Salesforce's displayed posting ages; not internship term.
        posted_at=datetime.combine(date.fromisoformat(published), time(), UTC),
        degrees=required_degrees(description),
    )


def _search(client: httpx.Client, base: str, facets: dict[str, list[str]], offset: int = 0) -> dict:
    response = client.post(base + "/jobs", json={
        "appliedFacets": facets, "limit": PAGE_SIZE, "offset": offset, "searchText": "",
    })
    response.raise_for_status()
    page = response.json()
    total, rows = page["total"], page["jobPostings"]
    if type(total) is not int or total < 0:
        raise ValueError("invalid result total")
    if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
        raise ValueError("invalid result page")
    for row in rows:
        path = _text(row["externalPath"])
        if not re.fullmatch(r"/job/[^?#]+", path) or "/../" in path:
            raise ValueError("invalid job detail path")
    return page


def _collect_rows(client: httpx.Client, base: str, facets: dict[str, list[str]],
                  first: dict, pool: ThreadPoolExecutor) -> list[dict]:
    total = first["total"]
    if total >= RESULT_WINDOW:
        raise ValueError("potentially capped result window; completeness unverified")
    pages = [first, *pool.map(lambda offset: _search(client, base, facets, offset),
                             range(PAGE_SIZE, total, PAGE_SIZE))]
    return _validated_rows(pages, total)


def _validated_rows(pages: list[dict], total: int) -> list[dict]:
    """Validate ordered pages using the independently established result count."""
    rows = []
    for offset, page in enumerate(pages):
        if page["total"] not in (0, total):
            raise ValueError("result total changed during pagination")
        expected = min(PAGE_SIZE, max(0, total - offset * PAGE_SIZE))
        if len(page["jobPostings"]) != expected:
            raise ValueError("page count does not match initial total")
        rows.extend(page["jobPostings"])
    if len({row["externalPath"] for row in rows}) != len(rows):
        raise ValueError("repeated job in search results")
    return rows


def _facet_counts(page: dict, parameter: str) -> dict[str, int]:
    facet = next((f for f in page["facets"] if f["facetParameter"] == parameter), None)
    if facet is None or not isinstance(facet["values"], list) or not facet["values"]:
        raise ValueError(f"missing coverage facet {parameter}")
    counts = {}
    for value in facet["values"]:
        identifier, count = _text(value["id"]), value["count"]
        if identifier in counts or type(count) is not int or count <= 0:
            raise ValueError(f"invalid coverage facet {parameter}")
        counts[identifier] = count
    return counts


def _partition_rows(client: httpx.Client, base: str, first: dict,
                    parameter: str, pool: ThreadPoolExecutor) -> list[dict]:
    categories = _facet_counts(first, parameter)
    time_types = _facet_counts(first, "timeType")
    expected = sum(categories.values())
    if expected < first["total"] or expected != sum(time_types.values()):
        raise ValueError("category counts do not cover independent time-type total")
    if len(categories) > 64 or any(count >= RESULT_WINDOW for count in categories.values()):
        raise ValueError("category partitions exceed verified result window")
    # Interleave pages from every category in one request pool. In particular,
    # small categories don't wait for the largest category to finish, and no
    # category coordinator occupies a worker while waiting for its own pages.
    requests = [
        (identifier, offset)
        for offset in range(0, max(categories.values()), PAGE_SIZE)
        for identifier, count in categories.items() if offset < count
    ]
    pages_by_category: dict[str, list[dict]] = {identifier: [] for identifier in categories}
    pages = pool.map(lambda request: _search(
        client, base, {parameter: [request[0]]}, request[1]
    ), requests)
    for (identifier, _), page in zip(requests, pages, strict=True):
        pages_by_category[identifier].append(page)
    rows = []
    for identifier, count in categories.items():
        category_pages = pages_by_category[identifier]
        if category_pages[0]["total"] != count:
            raise ValueError("category count changed or filter was ignored")
        rows.extend(_validated_rows(category_pages, count))
    paths = {row["externalPath"] for row in rows}
    if len(paths) != expected:
        raise ValueError("category partitions overlap or have incomplete coverage")
    if not {row["externalPath"] for row in first["jobPostings"]} <= paths:
        raise ValueError("unfiltered jobs missing from category coverage")
    final = _search(client, base, {})
    if (final["total"] != first["total"]
            or _facet_counts(final, parameter) != categories
            or _facet_counts(final, "timeType") != time_types):
        raise ValueError("board counts changed during category scan; retry board")
    return rows


def _filter_value(page: dict, parameter: str, label: str) -> tuple[str, int] | None:
    """Resolve a configured display label to the tenant's current ID and count."""
    facets = [f for f in page.get("facets", []) if f["facetParameter"] == parameter]
    if not facets:
        return None
    if len(facets) != 1 or not isinstance(facets[0]["values"], list):
        raise ValueError("invalid native filter facet")
    matches = [value for value in facets[0]["values"] if value.get("descriptor") == label]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("ambiguous native filter label")
    value = matches[0]
    identifier, count = _text(value["id"]), value["count"]
    if type(count) is not int or count < 0:
        raise ValueError("invalid native filter count")
    return identifier, count


def _filtered_rows(client: httpx.Client, base: str, first: dict,
                   board: Board, pool: ThreadPoolExecutor) -> list[dict] | None:
    selected = _filter_value(first, board.filter_facet, board.filter_value)
    if selected is None:
        print(f"::warning::{board.key}: native filter {board.filter_value!r} unavailable; "
              "using complete unfiltered scan")
        return None
    identifier, count = selected
    facets = {board.filter_facet: [identifier]}
    page = _search(client, base, facets)
    if page["total"] != count:
        raise ValueError("native filter count changed or filter was ignored")
    rows = _collect_rows(client, base, facets, page, pool)
    final = _search(client, base, {})
    if _filter_value(final, board.filter_facet, board.filter_value) != selected:
        raise ValueError("native filter changed during scan; retry board")
    print(f"{board.key}: native filter {board.filter_facet}={board.filter_value!r}")
    return rows


def fetch_workday(client: httpx.Client, board: Board) -> list[Posting]:
    base = f"https://{board.host}/wday/cxs/{board.slug}"
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            search_started = perf_counter()
            first = _search(client, base, {})
            rows = _filtered_rows(client, base, first, board, pool) if board.filter_facet else None
            if rows is None:
                if first["total"] >= RESULT_WINDOW and board.partition_facet:
                    rows = _partition_rows(client, base, first, board.partition_facet, pool)
                else:
                    rows = _collect_rows(client, base, {}, first, pool)
            print(f"{board.key}: search scan {perf_counter() - search_started:.2f}s, "
                  f"{len(rows)} rows")
            if board.partition_facet or board.filter_facet:
                # Reuse local title rules before spending requests on job details;
                # native filtering does not replace eligibility/classification.
                candidates = []
                for row in rows:
                    title = _text(row["title"])
                    if is_intern_title(title) and is_undergrad_title(title):
                        candidates.append(row)
            else:
                candidates = rows  # Preserve the small-board detail validation policy.
            if board.partition_facet or board.filter_facet:
                print(f"{board.key}: verified {len(rows)} search rows, "
                      f"{len(candidates)} title-eligible detail requests")
            details_started = perf_counter()
            postings = list(pool.map(lambda row: _detail(
                client, base + row["externalPath"], board
            ), candidates))
            print(f"{board.key}: details {perf_counter() - details_started:.2f}s, "
                  f"{len(postings)} postings")
            return postings
    except (httpx.HTTPError, KeyError, TypeError, ValueError, AttributeError) as e:
        raise SourceError(f"{board.key}: incomplete or invalid Workday response ({e})") from e
