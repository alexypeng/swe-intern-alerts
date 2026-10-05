"""Large Workday boards must prove complete coverage before yielding any jobs."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from intern_alerts.config import Board, Config
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
