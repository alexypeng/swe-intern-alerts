from dataclasses import replace
from datetime import UTC, datetime

from intern_alerts.dedup import SeenIndex
from intern_alerts.models import Posting
from intern_alerts.state import Record

NOW = datetime(2026, 10, 4, tzinfo=UTC)

GREENHOUSE = Posting(
    source="greenhouse",
    board_key="greenhouse:stripe",
    job_id="8128745",
    company="Stripe",
    title="Software Engineer, Intern (Summer or Winter)",
    locations=("Seattle, San Francisco, New York",),
    url="https://stripe.com/jobs/search?gh_jid=8128745",
    posted_at=NOW,
)

# The same job as Simplify lists it: different ID, title wording, and location format.
SIMPLIFY = Posting(
    source="simplify",
    board_key="simplify:stripe",
    job_id="7e914cf5-64bf-41bb-a680-71b7d7df80f6",
    company="Stripe",
    title="Software Engineer Intern - Summer or Winter",
    locations=("Seattle, WA", "SF", "NYC"),
    url="https://stripe.com/jobs/search?gh_jid=8128745&utm_source=Simplify",
    posted_at=NOW,
    category="Software",
)


def index_of(*postings):
    return SeenIndex(Record.from_posting(p) for p in postings)


def test_new_posting():
    assert SeenIndex().seen_by(GREENHOUSE) is None


def test_id_match():
    assert index_of(GREENHOUSE).seen_by(replace(GREENHOUSE, title="Renamed")) == "id"


def test_url_match_across_sources():
    assert index_of(GREENHOUSE).seen_by(SIMPLIFY) == "url"


def test_fields_match_when_url_differs():
    other_url = replace(GREENHOUSE, job_id="999", url="https://stripe.com/other")
    assert index_of(GREENHOUSE).seen_by(other_url) == "fields"


def test_same_company_different_job_is_new():
    different = replace(GREENHOUSE, job_id="999", url="https://stripe.com/other", title="Data Intern")
    assert index_of(GREENHOUSE).seen_by(different) is None


def test_same_job_id_at_different_company_is_new():
    other = replace(GREENHOUSE, company="Ramp", url="https://ramp.com/x", title="Other")
    assert index_of(GREENHOUSE).seen_by(other) is None


def test_second_copy_in_same_run_is_caught():
    index = SeenIndex()
    assert index.seen_by(GREENHOUSE) is None
    index.add(Record.from_posting(GREENHOUSE))  # chosen for announcement
    assert index.seen_by(SIMPLIFY) == "url"


def test_missing_url_never_matches_by_url():
    a = replace(GREENHOUSE, job_id="1", url="", title="A")
    b = replace(GREENHOUSE, job_id="2", url="", title="B")
    assert index_of(a).seen_by(b) is None
