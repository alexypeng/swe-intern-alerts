"""Extract explicitly required education from Workday description paragraphs."""

import re
from html.parser import HTMLParser

from intern_alerts.normalize import normalize_text

BLOCK_TAGS = {"p", "li", "div", "br", "h1", "h2", "h3", "h4"}
REQUIREMENT = re.compile(
    r"\b(?:pursuing|pursue|enrolled|enrollment|student|students|studying|"
    r"working toward|must|required|minimum)\b"
)
BACHELOR = re.compile(r"\b(?:bachelors?|b\s*s(?:\s*c)?|undergrad(?:uate)?)\b")
ASSOCIATE = re.compile(r"\bassociates?\b")
MASTER = re.compile(r"\b(?:masters?|m\s*s(?:\s*c)?|mba)\b")
MASTER_CONTEXT = re.compile(
    r"\b(?:degree|education|masters|master s|master of|master in|mba|m\s*s(?:\s*c)?|"
    r"pursuing|enrolled|enrollment|student|students|studying)\b"
)
DOCTOR = re.compile(r"\b(?:ph\s*d|doctoral|doctorate)\b")
PREFERRED = re.compile(r"\b(?:preferred|preferably|nice to have|ways to stand out|bonus)\b")
REQUIRED_HEADING = re.compile(r"^(?:what we need to see|required qualifications|requirements)$")


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self.pending: list[str] = []

    def flush(self):
        text = normalize_text("".join(self.pending))
        if text:
            self.paragraphs.append(text)
        self.pending.clear()

    def handle_starttag(self, tag, attrs):
        if tag in BLOCK_TAGS:
            self.flush()

    def handle_endtag(self, tag):
        if tag in BLOCK_TAGS:
            self.flush()

    def handle_data(self, data):
        self.pending.append(data)


def required_degrees(description: str) -> tuple[str, ...]:
    parser = _Paragraphs()
    parser.feed(description)
    parser.flush()
    degrees: set[str] = set()
    graduate_only: set[str] = set()
    preferred_section = False
    required_section = False
    for paragraph in parser.paragraphs:
        if REQUIRED_HEADING.fullmatch(paragraph):
            preferred_section = False
            required_section = True
            continue
        # Workday descriptions use a separate preferred-qualifications section.
        if PREFERRED.search(paragraph):
            if len(paragraph.split()) <= 8:
                preferred_section = True
            continue
        if preferred_section or not (required_section or REQUIREMENT.search(paragraph)):
            continue
        clause = set()
        if BACHELOR.search(paragraph):
            clause.add("Bachelor's")
        if ASSOCIATE.search(paragraph):
            clause.add("Associate's")
        if MASTER.search(paragraph) and MASTER_CONTEXT.search(paragraph):
            clause.add("Master's")
        if DOCTOR.search(paragraph):
            clause.add("PhD")
        degrees.update(clause)
        if clause and not clause & {"Bachelor's", "Associate's"}:
            graduate_only.update(clause)
    # A generic introductory BS/MS/PhD paragraph cannot override a specific grad-only
    # requirement later in the description. Unknown requirements retain existing policy.
    return tuple(sorted(graduate_only or degrees))
