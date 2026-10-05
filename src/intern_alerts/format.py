"""Builds one channel's Discord messages: postings grouped under region headers."""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from intern_alerts.classify import CANADA, EUROPE, REGIONS, REMOTE, UK, UNSPECIFIED, US
from intern_alerts.models import Posting

MAX_LENGTH = 2000  # Discord's limit for a message's content
MAX_LOCATIONS = 3
MAX_TITLE = 300
SEPARATOR = "\n\n"  # blank line between postings, and before each region header

HEADERS = {
    US: "## 🇺🇸 US",
    CANADA: "## 🇨🇦 Canada",
    EUROPE: "## 🇪🇺 Europe",
    UK: "## 🇬🇧 UK",
    REMOTE: "## 🌐 Remote",
    UNSPECIFIED: "## 📍 Location not specified",
}


@dataclass
class Message:
    content: str
    # Postings first shown in this message. Record them as seen once it is sent.
    postings: list[Posting] = field(default_factory=list)


def escape(text: str) -> str:
    return re.sub(r"([\\*_~`\[\]|])", r"\\\1", text)


def posting_block(posting: Posting) -> str:
    title = posting.title if len(posting.title) <= MAX_TITLE else posting.title[:MAX_TITLE] + "…"
    url = posting.url.replace(" ", "%20").replace(">", "%3E")
    locations = [escape(loc) for loc in posting.locations[:MAX_LOCATIONS]]
    if len(posting.locations) > MAX_LOCATIONS:
        locations.append(f"+{len(posting.locations) - MAX_LOCATIONS} more")
    date = f"{posting.posted_at:%b} {posting.posted_at.day}"
    return (
        f"**{escape(posting.company)}** — [{escape(title)}](<{url}>)\n"
        f"{' · '.join(locations)} · {date}"
    )


def build_messages(items: Iterable[tuple[Posting, frozenset[str]]]) -> list[Message]:
    """items: each posting with the regions it belongs to, all for the same channel."""
    by_region: dict[str, list[Posting]] = {region: [] for region in REGIONS}
    for posting, regions in items:
        for region in regions:
            by_region[region].append(posting)

    # Units are never split across messages. A region header travels with its first posting.
    units: list[tuple[str, Posting]] = []
    for region in REGIONS:
        postings = sorted(by_region[region], key=lambda p: (-p.posted_at.timestamp(), p.company, p.title))
        for i, posting in enumerate(postings):
            text = posting_block(posting)
            if i == 0:
                text = f"{HEADERS[region]}\n{text}"
            units.append((text, posting))

    messages: list[Message] = []
    current: Message | None = None
    shown: set[Posting] = set()
    for text, posting in units:
        if current is not None:
            if len(current.content) + len(SEPARATOR) + len(text) <= MAX_LENGTH:
                current.content += SEPARATOR + text
            else:
                current = None
        if current is None:
            current = Message(content=text[:MAX_LENGTH])
            messages.append(current)
        if posting not in shown:
            shown.add(posting)
            current.postings.append(posting)
    return messages
