"""Shared data shapes used across the pipeline."""

from dataclasses import dataclass
from datetime import datetime

# Job-type channels. Each has a matching WEBHOOK_<NAME> secret.
CHANNELS = ("swe", "data_ml", "hardware", "quant", "other_eng", "product")


@dataclass(frozen=True)
class Posting:
    """One job posting, in the same shape regardless of which source it came from."""

    source: str  # "simplify", "greenhouse", or "ashby"
    board_key: str  # e.g. "greenhouse:stripe", "simplify:faang"
    job_id: str  # the source's own ID for this posting
    company: str
    title: str
    locations: tuple[str, ...]
    url: str
    posted_at: datetime  # UTC
    category: str | None = None  # Simplify only
    employment_type: str | None = None  # Ashby only
    degrees: tuple[str, ...] = ()  # Simplify only; empty means not stated
