"""Amazon candidate-query union, with complete partitions for manual audits."""

import json
import re
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from time import perf_counter

import httpx

from intern_alerts.classify import is_intern_title, is_undergrad_title
from intern_alerts.config import Board
from intern_alerts.models import Posting
from intern_alerts.sources import SourceError
from intern_alerts.sources.workday_education import required_degrees

SEARCH_URL = "https://www.amazon.jobs/en/search.json"
PAGE_SIZE, RESULT_CAP, WORKERS = 100, 10_000, 4
FACETS = ("business_category_facet", "normalized_country_code_facet")


def _text(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing required text")
    return value.strip()


def _identity(job: dict) -> str:
    job_id = _text(job["id_icims"])
    if not re.fullmatch(r"[A-Za-z0-9]+", job_id):
        raise ValueError("invalid job ID")
    if not re.fullmatch(rf"/en/jobs/{re.escape(job_id)}(?:/[^?#]*)?", _text(job["job_path"])):
        raise ValueError(f"job URL does not match its ID ({job_id})")
    return job_id


def parse_amazon(job: dict, board: Board) -> Posting:
    locations = job["locations"]
    if not isinstance(locations, list):
        raise ValueError("invalid locations")
    places = []
    for location in locations:
        location = json.loads(location) if isinstance(location, str) else location
        country = _text(location["normalizedCountryName"])
        city = location.get("normalizedCityName") or location.get("city")
        state = location.get("normalizedStateName")
        parts = [_text(value) for value in (city, state, country) if value]
        place = ", ".join(dict.fromkeys(parts))
        places.append(f"Remote - {place}" if location.get("type") == "REMOTE" else place)
    basic = job["basic_qualifications"]
    if not isinstance(basic, str):
        raise ValueError("invalid basic qualifications")
    _text(job["description"])
    published = datetime.strptime(" ".join(_text(job["posted_date"]).split()), "%B %d, %Y")
    return Posting(
        source="amazon", board_key=board.key, company=board.name, job_id=_identity(job),
        title=_text(job["title"]), locations=tuple(dict.fromkeys(places or [""])),
        url="https://www.amazon.jobs/en/jobs/" + _identity(job),
        # Amazon's legacy search exposes a calendar date, not a publication timestamp.
        posted_at=published.replace(tzinfo=UTC),
        degrees=required_degrees("<h3>Required qualifications</h3>" + basic),
    )


def _search(client: httpx.Client, **params) -> dict:
    response = client.get(SEARCH_URL, params={"sort": "recent", **params})
    response.raise_for_status()
    page = response.json()
    if page["error"] is not None:
        raise ValueError(f"Amazon search error: {page['error']}")
    if type(page["hits"]) is not int or page["hits"] < 0 or not isinstance(page["jobs"], list):
        raise ValueError("invalid search count or jobs")
    return page


def _bounded_results(pool, fetch, items):
    """Keep at most WORKERS submitted/decoded pages, yielding in input order."""
    work = iter(items)
    pending = deque()
    for _ in range(WORKERS):
        if (item := next(work, None)) is not None:
            pending.append(pool.submit(fetch, item))
    while pending:
        yield pending.popleft().result()
        if (item := next(work, None)) is not None:
            pending.append(pool.submit(fetch, item))


def _counts(client: httpx.Client) -> tuple[dict[str, int], dict[str, int]]:
    page = _search(client, offset=0, result_limit=1,
                   **{"facets[]": ["business_category", "normalized_country_code"]})
    maps = []
    for name in FACETS:
        counts = {}
        if not isinstance(page["facets"][name], list):
            raise ValueError("invalid facet list")
        for item in page["facets"][name]:
            if not isinstance(item, dict) or len(item) != 1:
                raise ValueError("invalid facet entry")
            label, count = next(iter(item.items()))
            if not _text(label) or label in counts or type(count) is not int or count <= 0:
                raise ValueError("invalid or duplicate facet count")
            counts[label] = count
        maps.append(counts)
    total = sum(maps[0].values())
    if total != sum(maps[1].values()) or page["hits"] != min(total, RESULT_CAP):
        raise ValueError("independent search counts disagree")
    if len(page["jobs"]) != min(total, 1):
        raise ValueError("invalid count response length")
    if any(n >= RESULT_CAP for n in maps[0].values()):
        raise ValueError("business partition reaches result cap; further partitioning required")
    return maps[0], maps[1]


def fetch_amazon_full_scan(client: httpx.Client, board: Board) -> list[Posting]:
    started = perf_counter()
    try:
        groups, countries = _counts(client)
        snapshots = {}
        for attempt in range(3):
            changed = {g: n for g, n in groups.items()
                       if g not in snapshots or snapshots[g][0] != n}
            snapshots = {g: value for g, value in snapshots.items() if g in groups}
            scanned = {g: (n, set(), Counter(), []) for g, n in changed.items()}
            work = ((g, offset, n) for g, n in changed.items()
                    for offset in range(0, n, PAGE_SIZE))

            def fetch_page(item):
                group, offset, count = item
                page = _search(client, offset=offset, result_limit=PAGE_SIZE,
                               **{"business_category[]": group})
                if page["hits"] != count:
                    return group, None  # Refetch this whole partition against fresh counts.
                if len(page["jobs"]) != min(PAGE_SIZE, count - offset):
                    raise ValueError("partition page truncated")
                ids, places, postings = set(), Counter(), []
                for job in page["jobs"]:
                    job_id, title = _identity(job), _text(job["title"])
                    if job_id in ids or job["business_category"] != group:
                        raise ValueError("duplicate ID or wrong business partition")
                    ids.add(job_id)
                    places[_text(job["country_code"])] += 1
                    if is_intern_title(title) and is_undergrad_title(title):
                        postings.append(parse_amazon(job, board))
                return group, (ids, places, postings)

            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                for group, result in _bounded_results(pool, fetch_page, work):
                    if result is None:
                        scanned.pop(group, None)
                    elif group in scanned:
                        ids, places, candidates = result
                        _, seen, locations, postings = scanned[group]
                        if seen & ids:
                            raise ValueError("duplicate ID across search pages")
                        seen.update(ids)
                        locations.update(places)
                        postings.extend(candidates)
            for group in changed:
                snapshots.pop(group, None)
            snapshots.update(scanned)
            fresh_groups, fresh_countries = _counts(client)
            if (fresh_groups, fresh_countries) == (groups, countries) and len(snapshots) == len(groups):
                seen, locations, postings = set(), Counter(), []
                for group, count in groups.items():
                    n, ids, places, candidates = snapshots[group]
                    if n != count or len(ids) != count:
                        raise ValueError("partition coverage incomplete")
                    if seen & ids:
                        raise ValueError("duplicate ID across partitions")
                    seen.update(ids)
                    locations.update(places)
                    postings.extend(candidates)
                if len(seen) != sum(groups.values()) or dict(locations) != countries:
                    raise ValueError("partition coverage does not match independent counts")
                print(f"{board.key}: verified {len(seen)} search jobs, parsed {len(postings)} "
                      f"candidate postings in {perf_counter() - started:.2f}s ({attempt + 1} passes)")
                return postings
            # Country changes without business-count changes cannot identify stale partitions.
            if fresh_groups == groups and fresh_countries != countries:
                snapshots.clear()
            groups, countries = fresh_groups, fresh_countries
        raise ValueError("search counts did not stabilize after three passes")
    except (httpx.HTTPError, KeyError, TypeError, ValueError, AttributeError) as e:
        raise SourceError(f"{board.key}: incomplete search ({e})") from e


CANDIDATE_QUERIES = (
    ('native', {'is_intern[]': '1'}),
    ('intern', {'base_query': 'intern'}),
    ('internship', {'base_query': 'internship'}),
    ('co-op', {'base_query': 'co-op'}),
    ('coop', {'base_query': 'coop'}),
)


def fetch_amazon(client: httpx.Client, board: Board) -> list[Posting]:
    """Validate every selected query, not completeness of the entire job board."""
    started = perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for attempt in range(3):
                def first(query):
                    return _search(client, offset=0, result_limit=PAGE_SIZE, **query[1])

                initial = list(pool.map(first, CANDIDATE_QUERIES))
                if any(page['hits'] >= RESULT_CAP for page in initial):
                    print(f'{board.key}: candidate query reaches result cap; using complete scan')
                    return fetch_amazon_full_scan(client, board)
                totals = [page['hits'] for page in initial]
                rows = [[] for _ in initial]
                seen = [set() for _ in initial]
                changed = False

                def collect(index, offset, page):
                    nonlocal changed
                    if page['hits'] != totals[index]:
                        changed = True
                        return
                    if len(page['jobs']) != min(PAGE_SIZE, totals[index] - offset):
                        raise ValueError('candidate query page truncated')
                    for item in page['jobs']:
                        job_id = _identity(item)
                        _text(item['title'])
                        if job_id in seen[index]:
                            raise ValueError('duplicate ID within candidate query')
                        seen[index].add(job_id)
                        rows[index].append(item)

                for index, page in enumerate(initial):
                    collect(index, 0, page)
                work = ((index, offset) for index, total in enumerate(totals)
                        for offset in range(PAGE_SIZE, total, PAGE_SIZE))

                def page(item):
                    index, offset = item
                    return index, offset, _search(
                        client, offset=offset, result_limit=PAGE_SIZE,
                        **CANDIDATE_QUERIES[index][1],
                    )

                for result in _bounded_results(pool, page, work):
                    collect(*result)
                final = list(pool.map(first, CANDIDATE_QUERIES))
                if changed or [p['hits'] for p in final] != totals:
                    continue
                # Check the required final response too, even though its rows
                # aren't used as a second candidate snapshot.
                for total, response in zip(totals, final):
                    if len(response['jobs']) != min(PAGE_SIZE, total):
                        raise ValueError('final candidate query page truncated')
                unique = {}
                titles = {}
                for index, items in enumerate(rows):
                    if len(seen[index]) != totals[index]:
                        raise ValueError('candidate query coverage incomplete')
                    for item in items:
                        # Check title consistency before dropping a graduate-only
                        # copy; otherwise another query could supply an eligible
                        # version of the same ID and bypass the degree rule.
                        job_id, title = _identity(item), _text(item['title'])
                        if titles.setdefault(job_id, title) != title:
                            raise ValueError('job title changed between queries')
                        if not (is_intern_title(item['title']) and is_undergrad_title(item['title'])):
                            continue
                        posting = parse_amazon(item, board)
                        previous = unique.setdefault(posting.job_id, posting)
                        if previous != posting:
                            raise ValueError('candidate details changed between queries')
                print(f'{board.key}: verified candidate queries {dict(zip((q[0] for q in CANDIDATE_QUERIES), totals))}, '
                      f'parsed {len(unique)} unique candidates in {perf_counter() - started:.2f}s '
                      f'({attempt + 1} passes)')
                return list(unique.values())
        raise ValueError('candidate query counts did not stabilize after three passes')
    except (httpx.HTTPError, KeyError, TypeError, ValueError, AttributeError) as e:
        raise SourceError(f'{board.key}: incomplete candidate queries ({e})') from e
