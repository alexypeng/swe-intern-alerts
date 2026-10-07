"""Decides whether a posting is an internship, which channels it goes to, and its regions."""

import re
from dataclasses import dataclass

from intern_alerts.models import Posting
from intern_alerts.normalize import normalize_text

US, CANADA, UK, EUROPE, REMOTE = "US", "Canada", "UK", "Europe", "Remote"
# For postings whose location is vague ("Multiple Locations") and whose title names no place.
UNSPECIFIED = "Unspecified"
REGIONS = (US, CANADA, EUROPE, UK, REMOTE, UNSPECIFIED)  # display order in messages


@dataclass(frozen=True)
class Classification:
    channels: frozenset[str]
    regions: frozenset[str]
    unrecognized: tuple[str, ...]  # location strings no rule matched, for logging

    @property
    def announce(self) -> bool:
        return bool(self.channels and self.regions)


IGNORED = Classification(frozenset(), frozenset(), ())


def classify(posting: Posting) -> Classification:
    if not is_intern(posting) or not is_undergrad(posting):
        return IGNORED
    channels = job_channels(posting)
    if not channels:
        return IGNORED
    regions: set[str] = set()
    unrecognized = []
    vague = False
    for location in posting.locations:
        found = location_regions(location)
        if found:
            regions |= found
        elif is_vague_location(location):
            vague = True
        else:
            unrecognized.append(location)
    if vague and not regions:
        # e.g. "Software Engineer Intern - Austin, TX" with location "In-Office"
        regions = location_regions(posting.title) or {UNSPECIFIED}
    return Classification(frozenset(channels), frozenset(regions), tuple(unrecognized))


# Internship detection

INTERN_TITLE = re.compile(r"\b(intern|internship|co-op|coop)s?\b", re.IGNORECASE)

# Internship programs not aimed at university students, excluded from every source.
EXCLUDED_TITLE = re.compile(r"\bhigh school\b")


def is_intern_title(title: str) -> bool:
    """Shared title eligibility for title-based sources and early detail filtering."""
    return bool(INTERN_TITLE.search(title)) and not EXCLUDED_TITLE.search(normalize_text(title))


def is_intern(posting: Posting) -> bool:
    if EXCLUDED_TITLE.search(normalize_text(posting.title)):
        return False
    if posting.source == "simplify":
        return True  # Simplify only lists internships
    if posting.source == "ashby":
        return posting.employment_type == "Intern"
    if posting.source in ("lever", "smartrecruiters", "meta"):
        # Either signal counts: labels vary by company ("Intern", "Internship"), and some
        # internships are mislabelled "Full-time". Word boundaries keep out labels like
        # "International Office Entity".
        return bool(
            INTERN_TITLE.search(posting.employment_type or "")
            or INTERN_TITLE.search(posting.title)
        )
    return is_intern_title(posting.title)


# Degree level: only postings open to undergrads

UNDERGRAD_DEGREES = {"Bachelor's", "Associate's"}
# "graduate"/"grad" as whole words, so "undergraduate"/"undergrad" don't match.
GRAD_TITLE = re.compile(
    r"\b(?:phd|ph d|ms|msc|master|masters|mba|doctoral|doctorate|graduate|grad)\b"
)
UNDERGRAD_TITLE = re.compile(r"\b(?:bs|bsc|bachelor|bachelors|undergrad|undergraduate)\b")


def is_undergrad(posting: Posting) -> bool:
    if posting.degrees and not UNDERGRAD_DEGREES & set(posting.degrees):
        return False
    return is_undergrad_title(posting.title)


def is_undergrad_title(title: str) -> bool:
    title = normalize_text(title)
    return not (GRAD_TITLE.search(title) and not UNDERGRAD_TITLE.search(title))


# Job type

SIMPLIFY_CATEGORIES = {
    "Software": "swe",
    "Software Engineering": "swe",
    "AI/ML/Data": "data_ml",
    "Data Science, AI & Machine Learning": "data_ml",
    "Hardware": "hardware",
    "Hardware Engineering": "hardware",
    "Quant": "quant",
    "Quantitative Finance": "quant",
    "Product": "product",
    "Product Management": "product",
}

# Matched against the normalized title on word boundaries, allowing a plural "s".
CHANNEL_KEYWORDS = {
    "swe": [
        "software", "swe", "sde", "developer", "backend", "back end", "frontend", "front end",
        "full stack", "fullstack", "mobile", "ios", "android", "infrastructure", "devops", "sre",
        "security engineer",
    ],
    "data_ml": [
        "machine learning", "ml", "ai", "data science", "data scientist", "data engineer",
        "data engineering", "data analyst", "data analytics", "research scientist",
    ],
    "hardware": [
        "hardware", "firmware", "embedded", "electrical", "asic", "fpga", "rtl", "chip",
        "silicon", "pcb", "rf",
    ],
    "quant": ["quant", "quantitative", "trading", "trader"],
    "other_eng": [
        "mechanical", "civil", "chemical", "aerospace", "manufacturing", "industrial",
        "materials", "test engineer", "quality",
    ],
    "product": [
        "product manager", "product management", "apm", "product design", "product designer",
    ],
}


def _word_pattern(phrases: list[str]) -> re.Pattern[str]:
    alternatives = sorted((re.escape(p) for p in phrases), key=len, reverse=True)
    return re.compile(rf"\b(?:{'|'.join(alternatives)})s?\b")


CHANNEL_PATTERNS = {channel: _word_pattern(words) for channel, words in CHANNEL_KEYWORDS.items()}


def job_channels(posting: Posting) -> set[str]:
    if posting.source == "simplify":
        channel = SIMPLIFY_CATEGORIES.get(posting.category or "")
        return {channel} if channel else set()
    title = normalize_text(posting.title)
    # Amazon's Business Developer role is sales/business development, not software.
    swe_title = re.sub(r"\bbusiness developers?\b", "", title) if posting.source == "amazon" else title
    channels = {channel for channel, pattern in CHANNEL_PATTERNS.items()
                if pattern.search(swe_title if channel == "swe" else title)}
    # Meta's descriptions establish software infrastructure and manufacturing duties.
    if posting.source == "meta":
        if re.search(r"\bproduction engineers?\b", title):
            channels.add("swe")
        if re.search(r"\bdfx engineering\b", title):
            channels.add("other_eng")
    return channels


# Regions

US_STATES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california",
    "CO": "colorado", "CT": "connecticut", "DE": "delaware", "FL": "florida", "GA": "georgia",
    "HI": "hawaii", "ID": "idaho", "IL": "illinois", "IN": "indiana", "IA": "iowa",
    "KS": "kansas", "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland",
    "MA": "massachusetts", "MI": "michigan", "MN": "minnesota", "MS": "mississippi",
    "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada", "NH": "new hampshire",
    "NJ": "new jersey", "NM": "new mexico", "NY": "new york", "NC": "north carolina",
    "ND": "north dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon", "PA": "pennsylvania",
    "RI": "rhode island", "SC": "south carolina", "SD": "south dakota", "TN": "tennessee",
    "TX": "texas", "UT": "utah", "VT": "vermont", "VA": "virginia", "WA": "washington",
    "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming", "DC": "district of columbia",
}

CANADA_PROVINCES = {
    "AB": "alberta", "BC": "british columbia", "MB": "manitoba", "NB": "new brunswick",
    "NL": "newfoundland", "NS": "nova scotia", "NT": "northwest territories", "NU": "nunavut",
    "ON": "ontario", "PE": "prince edward island", "QC": "quebec", "SK": "saskatchewan",
    "YT": "yukon",
}

# Place names found anywhere in a normalized location string. Leave out names that are
# common in more than one region (e.g. Cambridge, Birmingham, Durham); the state, province,
# or country next to them decides instead.
PLACES = {
    US: [
        *US_STATES.values(), "united states", "usa", "us", "u s", "u s a",
        "new york city", "san francisco", "seattle", "austin", "boston", "chicago",
        "los angeles", "palo alto", "mountain view", "sunnyvale", "san jose", "santa clara",
        "menlo park", "cupertino", "redmond", "bellevue", "kirkland", "san diego", "denver",
        "boulder", "atlanta", "dallas", "houston", "miami", "pittsburgh", "philadelphia",
        "portland", "salt lake city", "phoenix", "raleigh", "detroit", "minneapolis",
        "nashville", "irvine", "san mateo", "foster city", "redwood city", "oakland",
        "berkeley", "brooklyn", "jersey city", "bay area", "silicon valley", "south sf",
    ],
    CANADA: [
        *CANADA_PROVINCES.values(), "canada", "toronto", "vancouver", "montreal", "waterloo",
        "ottawa", "calgary", "edmonton", "mississauga", "markham", "kitchener", "halifax",
        "winnipeg", "burnaby",
    ],
    UK: [
        "united kingdom", "uk", "u k", "england", "scotland", "wales", "northern ireland",
        "london", "edinburgh", "manchester", "bristol", "belfast", "glasgow", "oxford",
    ],
    EUROPE: [
        "europe", "ireland", "germany", "france", "netherlands", "spain", "italy",
        "switzerland", "sweden", "norway", "denmark", "finland", "poland", "portugal",
        "austria", "belgium", "czech republic", "czechia", "romania", "greece", "hungary",
        "estonia", "lithuania", "latvia", "luxembourg", "bulgaria", "croatia", "serbia",
        "ukraine", "slovakia", "slovenia", "dublin", "cork", "berlin", "munich", "hamburg",
        "frankfurt", "paris", "amsterdam", "madrid", "barcelona", "zurich", "geneva",
        "stockholm", "copenhagen", "oslo", "helsinki", "warsaw", "krakow", "lisbon", "milan",
        "rome", "vienna", "brussels", "prague", "bucharest", "athens", "budapest", "tallinn",
    ],
}

# Abbreviations only trusted when they are the whole location string ("LA" could be
# part of a non-US place name).
WHOLE_STRING_ABBREVIATIONS = {"nyc": US, "sf": US, "la": US, "dc": US}

# Two-letter state/province codes, only trusted right after a comma ("Austin, TX").
CODE_AFTER_COMMA = re.compile(r",\s*([A-Z]{2})\b")

PLACE_TO_REGION = {place: region for region, places in PLACES.items() for place in places}
PLACE_PATTERN = re.compile(
    rf"\b(?:{'|'.join(sorted(map(re.escape, PLACE_TO_REGION), key=len, reverse=True))})\b"
)
REMOTE_WORD = re.compile(r"\bremote\b")

# Location strings that say nothing about where the job is.
VAGUE_LOCATION = re.compile(
    r"^$|\b(?:multiple locations|various locations|blank|in office|flexible|any \w+ site|"
    r"tbd|to be determined)\b"
)


def is_vague_location(location: str) -> bool:
    return bool(VAGUE_LOCATION.search(normalize_text(location)))


def location_regions(location: str) -> set[str]:
    """Regions one location string belongs to. Empty means drop it (and log it)."""
    text = normalize_text(location)
    if text in WHOLE_STRING_ABBREVIATIONS:
        return {WHOLE_STRING_ABBREVIATIONS[text]}

    regions = {PLACE_TO_REGION[m.group(0)] for m in PLACE_PATTERN.finditer(text)}
    codes = CODE_AFTER_COMMA.findall(location)
    has_province = any(code in CANADA_PROVINCES for code in codes)
    for code in codes:
        if code == "CA" and has_province:
            continue  # "Toronto, ON, CA": country code for Canada, not California
        if code in US_STATES:
            regions.add(US)
        elif code in CANADA_PROVINCES:
            regions.add(CANADA)

    if REMOTE_WORD.search(text):
        # "Remote" alone, or remote in a listed region, goes under Remote only.
        # Remote somewhere else ("Remote (India)") is dropped.
        if regions or text == "remote":
            return {REMOTE}
        return set()
    return regions
