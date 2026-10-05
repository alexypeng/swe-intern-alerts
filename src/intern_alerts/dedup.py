"""Checks whether a posting was already announced: by ID, then URL, then company + title + location."""

from collections.abc import Iterable

from intern_alerts.models import Posting
from intern_alerts.normalize import normalize_url
from intern_alerts.state import Record


class SeenIndex:
    def __init__(self, records: Iterable[Record] = ()) -> None:
        self._ids: set[tuple[str, str]] = set()
        self._urls: set[str] = set()
        self._fields: set[tuple[str, str, str]] = set()
        for record in records:
            self.add(record)

    def add(self, record: Record) -> None:
        """Call as soon as a posting is chosen, so a second copy later in the same run is caught."""
        self._ids.add((record.company, record.job_id))
        if record.url:
            self._urls.add(normalize_url(record.url))
        self._fields.add((record.company, record.title, record.location))

    def seen_by(self, posting: Posting) -> str | None:
        """Which check matched ("id", "url", "fields"), or None if the posting is new."""
        candidate = Record.from_posting(posting)
        if (candidate.company, candidate.job_id) in self._ids:
            return "id"
        if candidate.url and candidate.url in self._urls:
            return "url"
        if (candidate.company, candidate.title, candidate.location) in self._fields:
            return "fields"
        return None
