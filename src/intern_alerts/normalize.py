"""Normalization shared by dedup and state, so both sides of a comparison match."""

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that only track where a click came from. All others (e.g. gh_jid) are kept,
# since some sites put the job ID in the query string.
TRACKING_PARAMS = frozenset({"ref", "source", "gh_src"})

# Hosts that serve the same postings under different names.
HOST_ALIASES = {"boards.greenhouse.io": "job-boards.greenhouse.io"}


def _is_tracking_param(name: str) -> bool:
    name = name.lower()
    return name.startswith("utm_") or name in TRACKING_PARAMS


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").removeprefix("www.")
    host = HOST_ALIASES.get(host, host)
    path = parts.path.rstrip("/")
    meta = re.fullmatch(r"/(?:jobs|profile/job_details)/(\d+)", path)
    if host == "metacareers.com" and meta:
        return f"https://metacareers.com/profile/job_details/{meta[1]}"
    amazon = re.fullmatch(r"/en/jobs/([A-Za-z0-9]+)(?:/[^/]+)?", path)
    if host == "amazon.jobs" and amazon:
        return f"https://amazon.jobs/en/jobs/{amazon[1]}"
    # Verified Workday copies differ by site, locale, title, and optional copy suffix.
    # Unknown requisition formats retain the ordinary URL comparison.
    tenant = re.fullmatch(r"([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com", host)
    requisition = re.search(r"/job/.+_(JR\d+)(?:-\d+)?$", path)
    if tenant and requisition:
        return f"https://{tenant[1]}.myworkdayjobs.com/job/{requisition[1]}"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(k)
    )
    return urlunsplit(("https", host, path, urlencode(query), ""))


def normalize_text(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^\w\s]|_", " ", text)
    return " ".join(text.split())


def normalize_locations(locations: tuple[str, ...] | list[str]) -> str:
    """One comparable string for a posting's locations, independent of their order."""
    return "; ".join(sorted({normalize_text(loc) for loc in locations}))
