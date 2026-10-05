import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from intern_alerts.classify import classify, is_intern
from intern_alerts.config import Board
from intern_alerts.sources import SourceError
from intern_alerts.sources.ashby import fetch_ashby, parse_ashby
from intern_alerts.sources.greenhouse import fetch_greenhouse, parse_greenhouse
from intern_alerts.sources.lever import fetch_lever, parse_lever
from intern_alerts.sources.simplify import fetch_simplify, parse_simplify
from intern_alerts.sources.smartrecruiters import fetch_smartrecruiters, parse_smartrecruiters

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
    assert p.board_key == "simplify:stripe"
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


# Lever

PALANTIR = Board(source="lever", slug="palantir", name="Palantir")
SERVICENOW = Board(source="smartrecruiters", slug="ServiceNow", name="ServiceNow")


def test_lever_maps_fields():
    p = parse_lever(load("lever.json"), PALANTIR)[0]
    assert p.source == "lever"
    assert p.board_key == "lever:palantir"
    assert p.company == "Palantir"
    assert p.title == "Forward Deployed Infrastructure Engineer, Internship - US Government"
    assert p.locations == ("Washington, D.C.",)
    assert p.url.startswith("https://jobs.lever.co/palantir/")
    assert p.employment_type == "Internship"
    assert p.posted_at.tzinfo == UTC


def test_lever_intern_by_label_or_title():
    by_title = {p.title: p for p in parse_lever(load("lever.json"), PALANTIR)}
    assert is_intern(by_title["Forward Deployed Infrastructure Engineer, Internship - US Government"])
    # Labelled Full-time, but the title says Internship.
    assert is_intern(by_title["Forward Deployed Software Engineer, Internship - AUS Government"])
    assert not is_intern(by_title["Administrative Business Partner"])


def test_lever_label_needs_whole_word():
    p = parse_lever(load("lever.json"), PALANTIR)[2]
    assert not is_intern(replace(p, employment_type="International Office Entity"))
    assert is_intern(replace(p, employment_type="Intern"))


def test_lever_remote_postings_marked_remote():
    data = load("lever.json")[:1]
    data[0]["workplaceType"] = "remote"
    data[0]["categories"]["allLocations"] = ["United States"]
    [p] = parse_lever(data, PALANTIR)
    assert p.locations == ("Remote - United States",)
    assert classify(p).regions == {"Remote"}


# SmartRecruiters


def test_smartrecruiters_maps_fields():
    by_type = {p.employment_type: p for p in parse_smartrecruiters(load("smartrecruiters.json")["content"], SERVICENOW)}
    intern = by_type["Intern"]
    assert intern.source == "smartrecruiters"
    assert intern.board_key == "smartrecruiters:ServiceNow"
    assert intern.url == f"https://jobs.smartrecruiters.com/ServiceNow/{intern.job_id}"
    assert intern.locations == ("Dublin, , Ireland",)
    assert is_intern(intern)
    assert not is_intern(by_type["Full-time"])


def test_smartrecruiters_coop_title_counts_as_intern():
    item = dict(load("smartrecruiters.json")["content"][1], name="Spring 2027 Co-Op - AI Systems")
    [p] = parse_smartrecruiters([item], SERVICENOW)
    assert is_intern(p)


def test_smartrecruiters_remote_location():
    item = dict(load("smartrecruiters.json")["content"][1])
    item["location"] = dict(item["location"], remote=True)
    [p] = parse_smartrecruiters([item], SERVICENOW)
    assert p.locations == ("Remote - Santa Clara, CALIFORNIA, United States",)


def test_smartrecruiters_fetches_every_page():
    base = load("smartrecruiters.json")["content"][1]
    jobs = [dict(base, id=str(i)) for i in range(250)]
    offsets = []

    def handler(request):
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        return httpx.Response(200, json={"totalFound": 250, "content": jobs[offset:offset + 100]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    postings = fetch_smartrecruiters(client, SERVICENOW)
    assert offsets == [0, 100, 200]
    assert len(postings) == 250


def test_smartrecruiters_error_raises_source_error():
    with pytest.raises(SourceError, match="smartrecruiters:ServiceNow"):
        fetch_smartrecruiters(client_returning(500, "down"), SERVICENOW)


def test_lever_error_raises_source_error():
    with pytest.raises(SourceError, match="lever:palantir"):
        fetch_lever(client_returning(404, "nope"), PALANTIR)
