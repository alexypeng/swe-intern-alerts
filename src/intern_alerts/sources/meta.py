"""Anonymous Meta job search, current query discovery, and JSON-LD details."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from html.parser import HTMLParser
from time import perf_counter
from urllib.parse import urlsplit

import httpx

from intern_alerts.classify import INTERN_TITLE, is_undergrad_title
from intern_alerts.config import Board
from intern_alerts.models import Posting
from intern_alerts.sources import SourceError

SEARCH_URL = "https://www.metacareers.com/jobsearch/"
GRAPHQL_URL = "https://www.metacareers.com/graphql"
SEARCH_QUERY = "CareersJobSearchResultsV2DataQuery"
COUNT_QUERY = "CareersJobSearchHideFiltersBarV2Query"
DETAIL_WORKERS = 4
MAX_JOBS = 5000
JOB_PATH = re.compile(r"/(?:profile/job_details|jobs)/(\d+)/?")
COUNTRIES = {
    "US": "United States", "CA": "Canada", "GB": "United Kingdom", "IE": "Ireland",
    "DE": "Germany", "FR": "France", "NL": "Netherlands", "CH": "Switzerland",
    "ES": "Spain", "IT": "Italy", "SE": "Sweden", "NO": "Norway", "DK": "Denmark",
    "FI": "Finland", "PL": "Poland", "PT": "Portugal", "AT": "Austria", "BE": "Belgium",
    "CZ": "Czechia", "RO": "Romania", "GR": "Greece", "HU": "Hungary", "EE": "Estonia",
    "LT": "Lithuania", "LV": "Latvia", "LU": "Luxembourg", "BG": "Bulgaria",
    "HR": "Croatia", "RS": "Serbia", "UA": "Ukraine", "SK": "Slovakia", "SI": "Slovenia",
    "IN": "India", "CN": "China", "SG": "Singapore", "IL": "Israel", "AU": "Australia",
}


def _text(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing or invalid required text")
    return value.strip()


def _job_id(url: str) -> str:
    parts = urlsplit(url)
    match = JOB_PATH.fullmatch(parts.path)
    if (parts.scheme != "https" or parts.hostname not in ("www.metacareers.com", "metacareers.com")
            or parts.port not in (None, 443) or parts.username or parts.password
            or parts.query or parts.fragment or not match):
        raise ValueError("invalid Meta job URL")
    return match[1]


class _Scripts(HTMLParser):
    def __init__(self, script_type="application/ld+json"):
        super().__init__()
        self.blocks: list[str] = []
        self.pending: list[str] | None = None
        self.script_type = script_type
        self.resources = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src") and attrs.get("data-bootloader-hash"):
            self.resources[attrs["data-bootloader-hash"]] = {"type": "js", "src": attrs["src"]}
        if tag == "link" and attrs.get("rel") == "stylesheet" and attrs.get("data-bootloader-hash"):
            self.resources[attrs["data-bootloader-hash"]] = {"type": "css"}
        if tag == "script" and attrs.get("type", "").lower() == self.script_type:
            self.pending = []

    def handle_data(self, data):
        if self.pending is not None:
            self.pending.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.pending is not None:
            self.blocks.append("".join(self.pending))
            self.pending = None


def _jobs(value):
    if isinstance(value, dict):
        types = value.get("@type", [])
        if types == "JobPosting" or isinstance(types, list) and "JobPosting" in types:
            yield value
        else:
            for child in value.values():
                yield from _jobs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _jobs(child)


def _country(address: dict) -> str:
    country = address.get("addressCountry", "")
    if isinstance(country, dict):
        country = country.get("name", "")
    if not isinstance(country, str):
        raise ValueError("invalid location country")
    country = country.strip()
    # Unknown ISO codes must not be mistaken for US states after a comma.
    return COUNTRIES.get(country, f"Country {country}" if len(country) == 2 else country)


def parse_meta(html: str, url: str, board: Board) -> Posting:
    job_id = _job_id(url)
    parser = _Scripts()
    parser.feed(html)
    jobs = [job for block in parser.blocks for job in _jobs(json.loads(block))]
    if len(jobs) != 1:
        raise ValueError("missing or ambiguous JobPosting data")
    job = jobs[0]
    if job["hiringOrganization"]["name"] != "Meta":
        raise ValueError("unexpected hiring organization")
    _text(job["description"])
    published = datetime.fromisoformat(_text(job["datePosted"]))
    if published.tzinfo is None:
        raise ValueError("posting date requires a timezone")
    employment = job.get("employmentType")
    if isinstance(employment, list):
        employment = " ".join(_text(value) for value in employment)
    if employment is not None:
        employment = _text(employment)
    places = job.get("jobLocation", [])
    if isinstance(places, dict):
        places = [places]
    if not isinstance(places, list):
        raise ValueError("invalid job locations")
    locations = []
    for place in places:
        address = place.get("address", {})
        name = place.get("name") or ", ".join(
            _text(address[key]) for key in ("addressLocality", "addressRegion") if address.get(key)
        )
        country = _country(address)
        locations.append(", ".join(part for part in (_text(name) if name else "", country) if part))
    if not locations and job.get("jobLocationType") == "TELECOMMUTE":
        requirements = job.get("applicantLocationRequirements", [])
        if isinstance(requirements, dict):
            requirements = [requirements]
        locations = [f"Remote - {_country({'addressCountry': r['name']})}" for r in requirements]
        if not locations:
            locations = ["Remote"]
    return Posting(
        source="meta", board_key=board.key, job_id=job_id, company=board.name,
        title=_text(job["title"]), locations=tuple(dict.fromkeys(locations or [""])),
        url=url, posted_at=published.astimezone(UTC), employment_type=employment,
    )


def _walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def parse_bootstrap(html: str) -> tuple[str, list[str]]:
    """Read the anonymous session token and search component's current JS assets."""
    parser = _Scripts("application/json")
    parser.feed(html)
    tokens = set()
    resources = dict(parser.resources)
    components = {}
    for block in parser.blocks:
        for value in _walk(json.loads(block)):
            if isinstance(value, list) and len(value) >= 3 and value[0] == "LSD":
                tokens.add(_text(value[2]["token"]))
            if isinstance(value, dict):
                resources.update(value.get("rsrcMap", {}))
                components.update(value.get("compMap", {}))
    if len(tokens) != 1:
        raise ValueError("missing or ambiguous anonymous session token")
    hashes = components["CPJobSearch.react"]["r"]
    if not isinstance(hashes, list) or not 0 < len(hashes) <= 16:
        raise ValueError("invalid search component resources")
    urls = []
    for key in hashes:
        resource = resources[key]
        if resource["type"] != "js":
            continue
        url = _text(resource["src"])
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname != "static.xx.fbcdn.net"
                or not parts.path.startswith("/rsrc.php/") or parts.username or parts.password):
            raise ValueError("unexpected search asset URL")
        urls.append(url)
    if not urls:
        raise ValueError("missing search JavaScript assets")
    return tokens.pop(), list(dict.fromkeys(urls))


def parse_query_ids(scripts: list[str]) -> dict[str, str]:
    """Extract current persisted-query IDs from named Relay modules, without JS execution."""
    found = {name: set() for name in (SEARCH_QUERY, COUNT_QUERY)}
    linked = set()
    for script in scripts:
        for module in re.split(r'(?=__d\(")', script):
            for name in found:
                operation = name + "_candidate_portalRelayOperation"
                if module.startswith(f'__d("{operation}",'):
                    found[name].update(re.findall(r'\b\w+\.exports\s*=\s*"(\d+)"', module))
                if (module.startswith(f'__d("{name}.graphql",')
                        and f'"{operation}"' in module):
                    linked.add(name)
    if any(len(ids) != 1 for ids in found.values()) or linked != set(found):
        raise ValueError("missing or ambiguous current search query IDs")
    return {name: ids.pop() for name, ids in found.items()}


def _query(client, token, ids, name):
    search_input = {
        "q": None, "divisions": [], "offices": [], "roles": [],
        "leadership_levels": [], "saved_jobs": [], "saved_searches": [],
        "sub_teams": [], "teams": [], "is_leadership": False,
        "is_remote_only": False, "sort_by_new": False, "results_per_page": None,
    }
    variables = {"search_input": search_input}
    if name == SEARCH_QUERY:
        variables.update(viewasUserID=None, isLoggedIn=False)
    else:
        search_input["page"] = 1
    response = client.post(GRAPHQL_URL, data={
        "lsd": token, "doc_id": ids[name], "variables": json.dumps(variables),
        "fb_api_req_friendly_name": name, "fb_api_caller_class": "RelayModern",
        "server_timestamps": "true",
    }, headers={"X-FB-LSD": token})
    response.raise_for_status()
    value = response.json()
    if value.get("errors") or value.get("extensions", {}).get("is_final") is not True:
        raise ValueError("failed or incomplete GraphQL query")
    return value["data"]["job_search_with_featured_jobs_v2"]


def _count(value):
    count = value["job_count"]
    if type(count) is not int or not 0 <= count <= MAX_JOBS:
        raise ValueError("invalid search count")
    return count


def parse_search(value: dict, expected: int) -> list[dict]:
    jobs = value["all_jobs"]
    if not isinstance(jobs, list) or len(jobs) != expected:
        raise ValueError("incomplete search results")
    ids = set()
    for job in jobs:
        job_id = _text(job["id"])
        if not re.fullmatch(r"\d+", job_id) or job_id in ids:
            raise ValueError("invalid or repeated search job ID")
        ids.add(job_id)
        _text(job["title"])
        for field in ("locations", "teams", "sub_teams"):
            values = job[field]
            if not isinstance(values, list):
                raise ValueError(f"invalid search {field}")
            for item in values:
                _text(item)
    return jobs


def fetch_meta(client: httpx.Client, board: Board) -> list[Posting]:
    started = perf_counter()
    try:
        response = client.get(SEARCH_URL)
        response.raise_for_status()
        token, urls = parse_bootstrap(response.text)

        def asset(url):
            response = client.get(url)
            response.raise_for_status()
            return response.text

        with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
            ids = parse_query_ids(list(pool.map(asset, urls)))
            count = _count(_query(client, token, ids, COUNT_QUERY))
            jobs = parse_search(_query(client, token, ids, SEARCH_QUERY), count)
            # Search returns the whole list; the frontend alone paginates it.
            # Use either the title or an explicit internship team signal. Do not
            # constrain discovery to Meta's native filter or skip channel/region
            # mismatches here: shared classification still owns those rules.
            candidates = [
                job for job in jobs
                if INTERN_TITLE.search(job["title"] + " " + " ".join(job["teams"]))
                and is_undergrad_title(job["title"])
            ]

            def detail(job):
                url = f"https://www.metacareers.com/profile/job_details/{job['id']}/"
                for attempt in range(2):
                    try:
                        response = client.get(url)
                        response.raise_for_status()
                        if _job_id(str(response.url)) != job["id"]:
                            raise ValueError("job redirected to another posting")
                        posting = parse_meta(response.text, url, board)
                        if posting.title != job["title"].strip():
                            raise ValueError("search/detail title changed")
                        # An explicit search team is also an internship label.
                        if INTERN_TITLE.search(" ".join(job["teams"])):
                            posting = replace(posting, employment_type="Internship")
                        return posting
                    except (httpx.HTTPError, KeyError, TypeError, ValueError, AttributeError) as e:
                        if attempt:
                            raise ValueError(f"job {job['id']}: {e}") from e

            postings = list(pool.map(detail, candidates))
        if _count(_query(client, token, ids, COUNT_QUERY)) != count:
            raise ValueError("search count changed during scan")
        print(f"{board.key}: verified {count} search jobs, fetched {len(candidates)} "
              f"candidate details in {perf_counter() - started:.2f}s")
        return postings
    except (httpx.HTTPError, KeyError, TypeError, ValueError, AttributeError) as e:
        raise SourceError(f"{board.key}: incomplete or invalid Meta response ({e})") from e
