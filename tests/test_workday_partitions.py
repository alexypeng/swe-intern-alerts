"""Large Workday boards must prove complete coverage before yielding any jobs."""

import json
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Lock

import httpx
import pytest

from intern_alerts.config import Board, Config
from intern_alerts.classify import classify
from intern_alerts.main import run
from intern_alerts.sources import SourceError
from intern_alerts.sources.workday import fetch_workday
from intern_alerts.state import State

BOARD = Board("workday", "nvidia/NVIDIAExternalCareerSite", "NVIDIA",
              "nvidia.wd5.myworkdayjobs.com", "jobFamilyGroup")
DETAIL = json.loads((Path(__file__).parent / "fixtures/workday.json").read_text())["jobPostingInfo"]


class PartitionWeb:
    def __init__(self):
        self.groups = {"engineering": [], "university": []}
        for i in range(2001):
            group = "engineering" if i < 1200 else "university"
            title = f"Software Intern {i}" if i in (0, 1200) else "Staff Software Engineer"
            if i == 1:
                title = "Software Intern - PhD"
            self.groups[group].append({"title": title,
                "externalPath": f"/job/US/Role_JR{i}"})
        self.details = []
        self.failure = None
        self.root_requests = 0

    def facets(self):
        total = sum(len(rows) for rows in self.groups.values())
        return [
            {"facetParameter": "jobFamilyGroup", "values": [
                {"id": key, "count": len(rows)} for key, rows in self.groups.items()
            ]},
            {"facetParameter": "timeType", "values": [
                {"id": "full", "count": total - 2}, {"id": "part", "count": 2},
            ]},
        ]

    def handler(self, request):
        if request.url.host == "simplify.test":
            return httpx.Response(200, json=[])
        if request.method == "GET":
            self.details.append(request.url.path)
            if self.failure == "detail":
                return httpx.Response(503)
            row = next(row for rows in self.groups.values() for row in rows
                       if request.url.path.endswith(row["externalPath"]))
            info = dict(DETAIL, title=row["title"],
                        jobDescription="<p>Must be enrolled in a B.S. degree program.</p>",
                        jobReqId=row["externalPath"].rsplit("_", 1)[1],
                        externalUrl=f"https://{BOARD.host}/site" + row["externalPath"])
            if self.failure == "missing_description":
                info.pop("jobDescription")
            return httpx.Response(200, json={"jobPostingInfo": info})
        body = json.loads(request.content)
        assert body["searchText"] == ""
        assert body["limit"] == 20
        selected, offset = body["appliedFacets"], body["offset"]
        if not selected:
            self.root_requests += 1
            facets = self.facets()
            if self.failure == "missing":
                facets.pop()
            if self.failure == "coverage":
                facets[1]["values"][0]["count"] += 1
            if self.failure == "cap":
                facets[0]["values"][0]["count"] = 2000
                facets[1]["values"][0]["count"] = 2799
            if self.failure == "changed" and self.root_requests > 1:
                facets[0]["values"][0]["count"] -= 1
            rows = deepcopy(self.groups["engineering"][:20])
            if self.failure == "uncovered":
                rows[0]["externalPath"] = "/job/US/Uncovered_JR9999"
            return httpx.Response(200, json={"total": 2000, "facets": facets,
                                           "jobPostings": rows})
        group = selected["jobFamilyGroup"][0]
        rows = deepcopy(self.groups[group][offset:offset + 20])
        total = len(self.groups[group]) if not offset else 0
        if group == "university":
            if self.failure == "http":
                return httpx.Response(503)
            if self.failure == "ignored":
                total = 2000
            if self.failure == "overlap" and not offset:
                rows[0] = self.groups["engineering"][0]
            if self.failure == "empty" and offset == 20:
                rows = []
            if self.failure == "title" and not offset:
                rows[0]["title"] = ""
        return httpx.Response(200, json={"total": total, "jobPostings": rows})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def test_capped_board_reads_all_categories_and_details_only_for_eligible_titles():
    web = PartitionWeb()
    with web.client() as client:
        postings = fetch_workday(client, BOARD)
    assert {p.job_id for p in postings} == {"JR0", "JR1200"}
    assert len(web.details) == 2
    assert web.root_requests == 2  # Re-check board counts after the complete scan.


def test_category_pages_share_four_workers_and_preserve_category_order():
    web = PartitionWeb()
    rows = [row for group in web.groups.values() for row in group]
    web.groups = {
        "engineering": rows[:500], "university": rows[500:1000],
        "sales": rows[1000:1500], "operations": rows[1500:],
    }
    barrier = Barrier(4, timeout=5)
    lock = Lock()
    active = peak = 0

    def handler(request):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            assert active <= 4
        try:
            if request.method == "POST":
                body = json.loads(request.content)
                if body["appliedFacets"] and body["offset"] == 0:
                    # All categories' first pages can start together. A serial
                    # category loop cannot satisfy this barrier.
                    barrier.wait()
            return web.handler(request)
        finally:
            with lock:
                active -= 1

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        postings = fetch_workday(client, BOARD)
    assert [posting.job_id for posting in postings] == ["JR0", "JR1200"]
    assert peak == 4
    assert web.root_requests == 2


def test_workday_logs_separate_search_and_detail_durations(capsys):
    web = PartitionWeb()
    with web.client() as client:
        fetch_workday(client, BOARD)
    output = capsys.readouterr().out
    assert f"{BOARD.key}: search scan " in output
    assert "2001 rows" in output
    assert f"{BOARD.key}: details " in output
    assert "2 postings" in output


@pytest.mark.parametrize("failure", [
    "missing", "coverage", "cap", "changed", "uncovered", "ignored",
    "overlap", "empty", "http", "title", "detail", "missing_description",
])
def test_unverified_category_coverage_or_detail_failure_rejects_whole_board(failure):
    web = PartitionWeb()
    web.failure = failure
    with web.client() as client, pytest.raises(SourceError, match=BOARD.key):
        fetch_workday(client, BOARD)


def test_large_board_without_opt_in_still_rejects_the_cap():
    web = PartitionWeb()
    with web.client() as client, pytest.raises(SourceError, match="capped"):
        fetch_workday(client, replace(BOARD, partition_facet=None))
    assert not web.details


def test_partition_failure_does_not_initialize_board_and_retry_is_silent():
    web = PartitionWeb()
    web.failure = "http"
    state = State()
    config = Config("https://simplify.test/jobs", frozenset(), (BOARD,))
    sent = []

    def poll():
        with web.client() as client:
            return run(config, state, client, datetime(2026, 10, 5, tzinfo=UTC),
                       {"swe": "https://discord.test/swe"}, save=lambda: None,
                       post=lambda c, u, message: sent.append(message))

    assert poll() == 0
    assert not state.records
    assert not state.is_board_polled(BOARD.key)
    web.failure = None
    assert poll() == 0
    assert state.is_board_polled(BOARD.key)
    assert len(state.records) == 2
    assert not sent
    web.groups["university"].append({"title": "Backend Software Intern",
                                     "externalPath": "/job/US/Backend_JR9999"})
    assert poll() == 0
    assert len(sent) == 1
    assert "JR9999>" in sent[0]
    assert "JR0>" not in sent[0]


FILTERED_BOARD = replace(BOARD, filter_facet="workerSubType", filter_value="Intern (Fixed Term)")


class NativeFilterWeb(PartitionWeb):
    def __init__(self):
        super().__init__()
        self.native_rows = self.groups["engineering"][:22] + self.groups["university"][:3]
        self.searches = []
        self.native_failure = None

    def handler(self, request):
        if request.method != "POST" or request.url.host == "simplify.test":
            return super().handler(request)
        body = json.loads(request.content)
        self.searches.append(body)
        selected, offset = body["appliedFacets"], body["offset"]
        if selected == {"workerSubType": ["intern-id"]}:
            if self.native_failure == "http" and offset:
                return httpx.Response(503)
            rows = deepcopy(self.native_rows[offset:offset + 20])
            total = len(self.native_rows) if not offset else 0
            if self.native_failure == "ignored":
                total = 2000
            if self.native_failure == "short" and offset:
                rows = []
            if self.native_failure == "repeat" and offset:
                rows[0] = self.native_rows[0]
            return httpx.Response(200, json={"total": total, "jobPostings": rows})
        response = super().handler(request)
        if not selected:
            page = response.json()
            count = len(self.native_rows)
            if self.native_failure == "changed" and self.root_requests > 1:
                count += 1
            values = [{"id": "intern-id", "descriptor": "Intern (Fixed Term)", "count": count}]
            if self.native_failure == "missing":
                values[0]["descriptor"] = "Renamed label"
            if self.native_failure == "ambiguous":
                values.append(dict(values[0], id="other-id"))
            page["facets"].append({"facetParameter": "workerSubType", "values": values})
            return httpx.Response(200, json=page)
        return response


def test_native_filter_is_applied_to_every_page_and_matches_complete_scan():
    filtered_web = NativeFilterWeb()
    with filtered_web.client() as client:
        filtered = fetch_workday(client, FILTERED_BOARD)
    complete_web = NativeFilterWeb()
    with complete_web.client() as client:
        complete = fetch_workday(client, BOARD)
    assert filtered == complete
    assert {p.job_id for p in filtered if classify(p).announce} == {"JR0", "JR1200"}
    pages = [body for body in filtered_web.searches if body["appliedFacets"]]
    assert {body["offset"] for body in pages} == {0, 20}
    assert all(body["appliedFacets"] == {"workerSubType": ["intern-id"]} for body in pages)
    assert filtered_web.root_requests == 2


@pytest.mark.parametrize("failure", ["http", "ignored", "short", "repeat", "changed", "ambiguous"])
def test_failed_native_filter_never_returns_partial_results(failure):
    web = NativeFilterWeb()
    web.native_failure = failure
    with web.client() as client, pytest.raises(SourceError, match=BOARD.key):
        fetch_workday(client, FILTERED_BOARD)
    assert not web.details


def test_missing_native_label_falls_back_to_complete_scan(capsys):
    web = NativeFilterWeb()
    web.native_failure = "missing"
    with web.client() as client:
        assert {p.job_id for p in fetch_workday(client, FILTERED_BOARD)} == {"JR0", "JR1200"}
    assert any(body["appliedFacets"].get("jobFamilyGroup") for body in web.searches)
    assert "using complete unfiltered scan" in capsys.readouterr().out


def test_empty_native_filter_is_successful_and_requests_no_details():
    web = NativeFilterWeb()
    web.native_rows.clear()
    with web.client() as client:
        assert fetch_workday(client, FILTERED_BOARD) == []
    assert not web.details


def test_native_detail_failure_leaves_first_poll_uninitialized_then_recovers_silently():
    web = NativeFilterWeb()
    web.failure = "detail"
    state = State()
    config = Config("https://simplify.test/jobs", frozenset(), (FILTERED_BOARD,))
    sent = []

    def poll():
        with web.client() as client:
            return run(config, state, client, datetime(2026, 10, 5, tzinfo=UTC),
                       {"swe": "https://discord.test/swe"}, save=lambda: None,
                       post=lambda c, u, message: sent.append(message))

    assert poll() == 0
    assert not state.boards and not state.records
    assert len(set(web.details)) == 2
    assert set(Counter(web.details).values()) == {2}  # Both details exhausted one retry.
    web.failure = None
    assert poll() == 0
    assert state.is_board_polled(BOARD.key)
    assert not sent
    assert {record.job_id for record in state.records} == {"JR0", "JR1200"}
