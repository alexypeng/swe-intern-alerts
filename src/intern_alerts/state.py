"""The persistent record of announced postings and polled boards (state.json)."""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from intern_alerts.models import Posting
from intern_alerts.normalize import normalize_locations, normalize_text, normalize_url

VERSION = 1
RETENTION = timedelta(days=365)


class StateError(Exception):
    pass


def to_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Record:
    """One announced posting. Text fields are stored normalized so comparisons are direct."""

    company: str
    job_id: str
    url: str
    title: str
    location: str
    first_seen: str  # UTC ISO 8601

    @classmethod
    def from_posting(cls, posting: Posting, first_seen: str = "") -> "Record":
        return cls(
            company=normalize_text(posting.company),
            job_id=posting.job_id,
            url=normalize_url(posting.url) if posting.url.strip() else "",
            title=normalize_text(posting.title),
            location=normalize_locations(posting.locations),
            first_seen=first_seen,
        )


@dataclass
class State:
    boards: dict[str, str] = field(default_factory=dict)  # board key -> first successful poll
    records: list[Record] = field(default_factory=list)

    def is_board_polled(self, board_key: str) -> bool:
        return board_key in self.boards

    def mark_board_polled(self, board_key: str, now: datetime) -> None:
        self.boards.setdefault(board_key, to_iso(now))

    def record(self, posting: Posting, now: datetime) -> Record:
        record = Record.from_posting(posting, first_seen=to_iso(now))
        self.records.append(record)
        return record

    def prune(self, now: datetime) -> int:
        """Drops records first seen more than a year ago. Returns how many were dropped."""
        cutoff = now - RETENTION
        kept = [r for r in self.records if datetime.fromisoformat(r.first_seen) >= cutoff]
        dropped = len(self.records) - len(kept)
        self.records = kept
        return dropped


def load_state(path: Path) -> State:
    """A missing file means the first run: empty state. A broken file is an error, not a reset."""
    if not path.exists():
        return State()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != VERSION:
            raise StateError(f"{path}: unsupported version {data.get('version')!r}")
        return State(
            boards=dict(data["boards"]),
            records=[Record(**r) for r in data["postings"]],
        )
    except (ValueError, KeyError, TypeError) as e:
        raise StateError(f"{path}: unreadable state file ({e!r})") from e


def save_state(state: State, path: Path) -> None:
    data = {
        "version": VERSION,
        "boards": dict(sorted(state.boards.items())),
        "postings": [asdict(r) for r in state.records],
    }
    # Write a temp file, then rename over the real one, so a crash can't leave it half-written.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
