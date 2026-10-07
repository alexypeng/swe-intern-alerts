"""Workday adapter and pipeline behavior against public-response fixtures."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from collections import Counter
from threading import Barrier, Lock

import httpx
import pytest

from intern_alerts.classify import classify
from intern_alerts.config import Board, Config
from intern_alerts.dedup import SeenIndex
from intern_alerts.main import run
from intern_alerts.normalize import normalize_url
from intern_alerts.sources import SourceError
from intern_alerts.sources.workday import fetch_workday, parse_workday
from intern_alerts.state import Record, State

BOARD = Board("workday", "salesforce/Futureforce_Internships", "Salesforce",
              "salesforce.wd12.myworkdayjobs.com")
NOW = datetime(2026, 10, 5, tzinfo=UTC)
# Selected public Salesforce detail fields, captured 2026-10-05; description omitted.
DETAIL = json.loads((Path(__file__).parent / "fixtures/workday.json").read_text())
URL = DETAIL["jobPostingInfo"]["externalUrl"]
COPY_URL = URL.replace("Futureforce_Internships", "External_Career_Site") + "-1"


class WorkdayWeb:
    def __init__(self):
        self.jobs = [dict(DETAIL["jobPostingInfo"], jobReqId=f"JR{i}", title=f"Software Intern {i}",
                          externalUrl=f"https://{BOARD.host}/site/job/US/Software-Intern_JR{i}")
                     for i in range(23)]
        self.offsets = []
        self.failure = None

    def handler(self, request):
        if request.url.host == "simplify.test":
            return httpx.Response(200, json=[])
        if request.method == "POST":
            body = json.loads(request.content)
            offset = body["offset"]
            self.offsets.append(offset)
            assert body["searchText"] == ""
            if offset and self.failure == "http":
                return httpx.Response(503)
            rows = [{"externalPath": f"/job/US/Software-Intern_{job['jobReqId']}"}
                    for job in self.jobs[offset:offset + 20]]
            if offset and self.failure == "empty":
                rows = []
            if offset and self.failure == "repeat":
                rows = [{"externalPath": "/job/US/Software-Intern_JR0"}]
            total = len(self.jobs) if offset == 0 else 0
            if self.failure == "cap":
                total = 2000
            return httpx.Response(200, json={"total": total, "jobPostings": rows})
        if self.failure == "detail":
            return httpx.Response(500)
        job_id = request.url.path.rsplit("_", 1)[1]
        job = next(j for j in self.jobs if j["jobReqId"] == job_id)
        return httpx.Response(200, json={"jobPostingInfo": job})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def test_complete_pagination_uses_initial_total_and_all_details():
    web = WorkdayWeb()
    with web.client() as client:
        postings = fetch_workday(client, BOARD)
    assert web.offsets == [0, 20]
    assert len(postings) == 23
    assert {p.job_id for p in postings} == {f"JR{i}" for i in range(23)}


@pytest.mark.parametrize("failure", [502, 503, 504, "timeout", "connection"])
def test_transient_detail_read_recovers_once_without_refetching_board(failure, monkeypatch):
    web = WorkdayWeb()
    attempts = Counter()
    delays = []
    monkeypatch.setattr("intern_alerts.sources.workday.sleep", delays.append)

    def handler(request):
        if request.method == "GET":
            attempts[request.url.path] += 1
            if request.url.path.endswith("_JR0") and attempts[request.url.path] == 1:
                if failure == "timeout":
                    raise httpx.ReadTimeout("temporary timeout", request=request)
                if failure == "connection":
                    raise httpx.ConnectError("temporary connection failure", request=request)
                return httpx.Response(failure)
        return web.handler(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        postings = fetch_workday(client, BOARD)
    assert [p.job_id for p in postings] == [f"JR{i}" for i in range(23)]
    assert web.offsets == [0, 20]
    assert sorted(attempts.values()) == [1] * 22 + [2]
    assert delays == [0.5]


@pytest.mark.parametrize("failure,expected_attempts", [
    (502, 2), (503, 2), (504, 2), ("timeout", 2),
    (404, 1), (500, 1), (429, 1), ("json", 1), ("metadata", 1),
])
def test_detail_retry_limit_and_nontransient_failures_reject_whole_board(
        failure, expected_attempts, monkeypatch):
    web = WorkdayWeb()
    attempts = []
    monkeypatch.setattr("intern_alerts.sources.workday.sleep", lambda _: None)

    def handler(request):
        if request.method == "GET" and request.url.path.endswith("_JR22"):
            attempts.append(request.url.path)
            if failure == "timeout":
                raise httpx.ReadTimeout("persistent timeout", request=request)
            if failure == "json":
                return httpx.Response(200, text="not JSON")
            if failure == "metadata":
                return httpx.Response(200, json={"jobPostingInfo": {}})
            return httpx.Response(failure)
        return web.handler(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match=BOARD.key):
            fetch_workday(client, BOARD)
    assert len(attempts) == expected_attempts


def test_retries_share_four_detail_workers_and_keep_result_order(monkeypatch):
    web = WorkdayWeb()
    web.jobs = web.jobs[:4]
    attempts = Counter()
    barrier = Barrier(4, timeout=5)
    lock = Lock()
    active = peak = 0
    monkeypatch.setattr("intern_alerts.sources.workday.sleep", lambda _: None)

    def handler(request):
        nonlocal active, peak
        if request.method != "GET":
            return web.handler(request)
        with lock:
            active += 1
            peak = max(peak, active)
            attempts[request.url.path] += 1
            attempt = attempts[request.url.path]
            assert active <= 4
        try:
            barrier.wait()  # Both initial attempts and retries overlap in the same pool.
            return httpx.Response(502) if attempt == 1 else web.handler(request)
        finally:
            with lock:
                active -= 1

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        postings = fetch_workday(client, BOARD)
    assert [p.job_id for p in postings] == [f"JR{i}" for i in range(4)]
    assert list(attempts.values()) == [2] * 4
    assert peak == 4


def test_verified_detail_preserves_required_fields_and_full_locations():
    posting = parse_workday(DETAIL, BOARD)
    assert posting.job_id == "JR340771"
    assert posting.url == URL
    assert posting.company == "Salesforce"
    assert posting.board_key == BOARD.key
    assert posting.posted_at == datetime(2026, 8, 31, tzinfo=UTC)
    assert len(posting.locations) == 8
    assert "California - San Francisco" in posting.locations
    # Fixture is labelled Full time: internship eligibility comes from its title.
    assert classify(posting).channels == {"swe"}
    assert classify(posting).regions == {"US"}
    assert not classify(replace(posting, title="Software Intern - PhD")).announce
    assert not classify(replace(posting, title="Software Engineer")).announce
    assert not classify(replace(posting, locations=("India - Hyderabad",))).announce


@pytest.mark.parametrize("description,eligible", [
    ("<p>What we need to see:</p><ul><li>Currently pursuing a PhD or Master degree.</li></ul>", False),
    ("<p>Must be actively enrolled in a university pursuing a B.S., M.S., or Ph.D. degree.</p>", True),
    ("<p>Currently pursuing a <b>Bachelor's</b> or Master’s degree.</p>", True),
    ("<p>Must be enrolled in a BSc degree program.</p>", True),
    ("<p>Currently pursuing an MSc degree.</p>", False),
    ("<p>Required qualifications:</p><ul><li>PhD in computer science.</li></ul>", False),
    ("<p>Required qualifications:</p><li>Bachelor's or Master's degree.</li>", True),
    ("<p>Required qualifications:</p><li>Experience with master data systems.</li>", True),
    ("<p>Currently pursuing a Master's or Ph.D.&nbsp;degree.</p>", False),
    ("<p>PhD degree preferred.</p>", True),
    ("<p>Ways to stand out:</p><p>Currently enrolled in a PhD degree program.</p>", True),
    ("<p>Preferred qualifications:</p><p>Currently enrolled in a PhD degree program.</p>"
     "<p>What we need to see:</p><p>Currently pursuing a Bachelor’s degree.</p>", True),
    ("<p>Must be enrolled in B.S., M.S., or Ph.D.</p>"
     "<p>What we need to see:</p><p>Currently pursuing a Master degree.</p>", False),
    ("<p>We offer flexible hours and mentorship.</p>", True),
])
def test_description_education_requirements_filter_graduate_only_and_keep_bachelors(description, eligible):
    data = deepcopy(DETAIL)
    data["jobPostingInfo"]["jobDescription"] = description
    assert classify(parse_workday(data, BOARD)).announce is eligible


@pytest.mark.parametrize("failure", ["http", "empty", "repeat", "cap", "detail"])
def test_incomplete_board_raises_without_returning_partial_results(failure):
    web = WorkdayWeb()
    web.failure = failure
    with web.client() as client, pytest.raises(SourceError, match=BOARD.key):
        fetch_workday(client, BOARD)


@pytest.mark.parametrize("field,value", [
    ("jobReqId", ""), ("title", None), ("location", ""),
    ("additionalLocations", "6 Locations"), ("startDate", "Posted Today"),
    ("externalUrl", "https://example.com/job/x"),
    ("posted", False), ("canApply", False),
])
def test_invalid_required_detail_fails_the_entire_fetch(field, value):
    web = WorkdayWeb()
    web.jobs[-1][field] = value
    with web.client() as client, pytest.raises(SourceError, match=BOARD.key):
        fetch_workday(client, BOARD)


def test_empty_board_is_a_successful_fetch():
    web = WorkdayWeb()
    web.jobs.clear()
    with web.client() as client:
        assert fetch_workday(client, BOARD) == []


@pytest.mark.parametrize("body", [
    {"total": True, "jobPostings": []},
    {"total": 0, "jobPostings": [{"externalPath": "/job/US/x_JR1"}]},
    {"total": 1, "jobPostings": [{"externalPath": "https://example.com/job/x"}]},
    {"total": 1, "jobPostings": None},
    {"total": 1},
    [],
])
def test_invalid_search_response_raises_source_error(body):
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=body)
    )) as client, pytest.raises(SourceError, match=BOARD.key):
        fetch_workday(client, BOARD)


def test_invalid_search_json_raises_source_error():
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html>Unavailable</html>")
    )) as client, pytest.raises(SourceError, match=BOARD.key):
        fetch_workday(client, BOARD)


def test_cross_site_copy_matches_historical_state_without_rewriting_display_url():
    posting = parse_workday(DETAIL, BOARD)
    historical = replace(Record.from_posting(posting), url=COPY_URL,
                         job_id="simplify-uuid", title="short title", location="sf")
    assert SeenIndex([historical]).seen_by(posting) == "url"
    assert posting.url == URL
    assert historical.url == COPY_URL
    assert normalize_url(COPY_URL) == normalize_url(URL)
    assert normalize_url(normalize_url(URL)) == normalize_url(URL)


@pytest.mark.parametrize("other", [
    URL.replace("JR340771", "JR340772"),
    URL.replace("salesforce.wd12", "other.wd12"),
    URL.replace("JR340771", "UNKNOWN340771"),
    URL.replace("myworkdayjobs.com", "myworkdayjobs.com.example.com"),
])
def test_different_tenant_requisition_and_unknown_formats_stay_distinct(other):
    assert normalize_url(other) != normalize_url(URL)


def test_failed_first_poll_retries_silently_then_announces_only_new_jobs():
    web = WorkdayWeb()
    web.failure = "http"
    state = State()
    config = Config("https://simplify.test/jobs", frozenset(), (BOARD,))
    sent = []

    def poll():
        with web.client() as client:
            return run(config, state, client, NOW, {"swe": "https://discord.test/swe"},
                       save=lambda: None, post=lambda c, u, message: sent.append(message))

    assert poll() == 0
    assert not state.is_board_polled(BOARD.key)
    assert not state.records
    web.failure = None
    assert poll() == 0
    assert state.is_board_polled(BOARD.key)
    assert len(state.records) == 23
    assert not sent
    new = deepcopy(web.jobs[0])
    new.update(jobReqId="JR999", title="Backend Software Intern",
               externalUrl=f"https://{BOARD.host}/site/job/US/Backend-Software-Intern_JR999")
    web.jobs.append(new)
    assert poll() == 0
    assert len(sent) == 1
    assert "JR999>" in sent[0]
    assert "JR0>" not in sent[0]
    assert len(state.records) == 24
    sent.clear()
    assert poll() == 0
    assert not sent
