import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from intern_alerts.config import Board
from intern_alerts.sources import SourceError
from intern_alerts.sources.ashby import fetch_ashby, parse_ashby
from intern_alerts.sources.greenhouse import fetch_greenhouse, parse_greenhouse
from intern_alerts.sources.simplify import fetch_simplify, parse_simplify

FIXTURES = Path(__file__).parent / "fixtures"
STRIPE = Board(source="greenhouse", slug="stripe", name="Stripe")
RAMP = Board(source="ashby", slug="ramp", name="Ramp")


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def client_returning(status: int, body: str) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, text=body)))


# Simplify


def test_simplify_keeps_only_active_visible_faang():
    postings = parse_simplify(load("simplify.json"), frozenset({"stripe", "google"}))
    # Google's listing is inactive, RTX isn't FAANG+, the hidden Stripe listing isn't visible.
    assert [p.job_id for p in postings] == [
        "7e914cf5-64bf-41bb-a680-71b7d7df80f6",
        "7bce6045-fde1-44d3-b2cc-1f56ae0dec16",
    ]


def test_simplify_maps_fields():
    p = parse_simplify(load("simplify.json"), frozenset({"stripe"}))[0]
    assert p.source == "simplify"
    assert p.board_key == "simplify:faang"
    assert p.company == "Stripe"
    assert p.title == "Software Engineer Intern - Summer or Winter"
    assert p.locations == ("Seattle, WA", "SF", "NYC")
    assert p.url == "https://stripe.com/jobs/search?gh_jid=8128745"
    assert p.category == "Software"
    assert p.posted_at == datetime.fromtimestamp(1788254097, UTC)


def test_simplify_faang_match_ignores_case():
    data = load("simplify.json")
    data[0]["company_name"] = "STRIPE "
    assert parse_simplify(data, frozenset({"stripe"}))[0].company == "STRIPE"


# Greenhouse


def test_greenhouse_returns_all_jobs_with_board_name():
    postings = parse_greenhouse(load("greenhouse.json"), STRIPE)
    assert len(postings) == 4  # intern filtering happens later, in classification
    assert {p.company for p in postings} == {"Stripe"}
    assert {p.board_key for p in postings} == {"greenhouse:stripe"}


def test_greenhouse_maps_fields():
    by_id = {p.job_id: p for p in parse_greenhouse(load("greenhouse.json"), STRIPE)}
    p = by_id["8194291"]
    assert p.title == "Data Analyst, Intern"
    assert p.locations == ("New York, Seattle, South San Francisco HQ",)
    assert p.url == "https://stripe.com/jobs/search?gh_jid=8194291"
    assert p.posted_at.tzinfo == UTC


# Ashby


def test_ashby_skips_unlisted_and_maps_fields():
    postings = parse_ashby(load("ashby.json"), RAMP)
    assert "Unlisted Role" not in {p.title for p in postings}
    by_title = {p.title: p for p in postings}
    assert by_title["Applied Scientist Intern"].employment_type == "Intern"
    security = by_title["Security Engineer, Cloud"]  # leading space stripped
    assert security.locations == (
        "New York, NY (HQ)",
        "Remote (Canada)",
        "Remote (US)",
        "Miami, FL",
    )
    assert security.company == "Ramp"
    assert security.url.startswith("https://jobs.ashbyhq.com/ramp/")


# Errors


def test_http_error_raises_source_error_naming_board():
    with pytest.raises(SourceError, match="greenhouse:stripe"):
        fetch_greenhouse(client_returning(404, "not found"), STRIPE)


def test_invalid_json_raises_source_error():
    with pytest.raises(SourceError, match="ashby:ramp"):
        fetch_ashby(client_returning(200, "<html>oops</html>"), RAMP)


def test_unexpected_shape_raises_source_error():
    with pytest.raises(SourceError, match="unexpected response format"):
        fetch_simplify(client_returning(200, '[{"id": "x"}]'), "https://x.test", frozenset())


def test_fetch_success_uses_parser():
    body = (FIXTURES / "ashby.json").read_text(encoding="utf-8")
    assert len(fetch_ashby(client_returning(200, body), RAMP)) == 2
