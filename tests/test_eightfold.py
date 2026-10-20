"""Complete PayPal discovery, failures, and integration with state/delivery."""

from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
from threading import Barrier, Lock

import httpx
import pytest

from intern_alerts.classify import classify
from intern_alerts.config import Board, Config
from intern_alerts.main import run
from intern_alerts.sources import SourceError
from intern_alerts.sources.eightfold import fetch_eightfold
from intern_alerts.state import State

BOARD = Board("eightfold", "paypal", "PayPal")
FIXTURE = json.loads((Path(__file__).parent / "fixtures/eightfold.json").read_text())


def job(job_id=1, title="Software Engineer Intern", **changes):
    row = deepcopy(FIXTURE["data"]["positions"][0])
    row.update(id=job_id, name=title, positionUrl=f"/careers/job/{job_id}",
               locations=["Austin, TX", "San Jose, CA"])
    row.update(changes)
    return row


def envelope(rows, count=None):
    data = deepcopy(FIXTURE)
    data["data"].update(positions=rows, count=len(rows) if count is None else count)
    return data


def fetch(handler):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return fetch_eightfold(client, BOARD)


def test_pagination_and_posting_mapping():
    requested = []

    def handler(request):
        assert request.url.path == "/api/pcsx/search"
        assert dict(request.url.params) == {
            "domain": "paypal.com", "query": "", "location": "",
            "start": request.url.params["start"], "sort_by": "timestamp",
        }
        start = int(request.url.params["start"])
        requested.append(start)
        return httpx.Response(200, json=envelope(rows[start:start+10], 23))

    rows = [job(i+1) for i in range(23)]
    postings = fetch(handler)
    assert sorted(requested) == [0, 0, 10, 20]
    assert [p.job_id for p in postings] == [str(i+1) for i in range(23)]
    assert postings[0].url == "https://paypal.eightfold.ai/careers/job/1"
    assert postings[0].locations == ("Austin, TX", "San Jose, CA")
    assert postings[0].posted_at == datetime(2026, 10, 9, tzinfo=UTC)
    assert postings[0].board_key == "eightfold:paypal"
    assert classify(postings[0]).announce


@pytest.mark.parametrize("change", [
    {"id": True}, {"id": -1}, {"postedTs": None}, {"postedTs": True},
    {"postedTs": float("inf")}, {"postedTs": 10**30},
    {"name": " "}, {"locations": []}, {"locations": [None]},
    {"positionUrl": "/careers/job/other"},
])
def test_invalid_row_rejects_whole_board(change):
    row = job()
    row.update(change)
    with pytest.raises(SourceError):
        fetch(lambda request: httpx.Response(200, text=json.dumps(envelope([row]))))


@pytest.mark.parametrize("defect", ["short", "duplicate", "count", "http", "json"])
def test_failed_later_page_discards_first_page(defect):
    rows = [job(i+1) for i in range(11)]

    def handler(request):
        if request.url.params["start"] == "0":
            return httpx.Response(200, json=envelope(rows[:10], 11))
        if defect == "http":
            return httpx.Response(503)
        if defect == "json":
            return httpx.Response(200, text="invalid")
        page = [] if defect == "short" else [rows[0] if defect == "duplicate" else rows[-1]]
        return httpx.Response(200, json=envelope(page, 12 if defect == "count" else 11))

    with pytest.raises(SourceError):
        fetch(handler)


@pytest.mark.parametrize("defect", ["status", "error", "fuzzy", "count", "oversized", "rows"])
def test_invalid_envelope_is_not_an_empty_success(defect):
    data = envelope([])
    if defect == "status":
        data["status"] = 500
    elif defect == "error":
        data["error"]["message"] = "upstream failure"
    elif defect == "fuzzy":
        data["data"]["resultsMetaData"]["usedFuzzSearch"] = True
    elif defect == "count":
        data["data"]["count"] = True
    elif defect == "oversized":
        data["data"]["count"] = 10001
    else:
        data["data"]["positions"] = None
    with pytest.raises(SourceError):
        fetch(lambda request: httpx.Response(200, json=data))


@pytest.mark.parametrize("changed_count", [False, True])
def test_final_response_detects_search_changes(changed_count):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json=envelope([job()]))
        return httpx.Response(200, json=envelope([job(2)], 2 if changed_count else 1))

    with pytest.raises(SourceError):
        fetch(handler)


def test_four_page_workers_and_deterministic_order():
    rows = [job(i+1) for i in range(50)]
    barrier, lock = Barrier(4, timeout=5), Lock()
    active = peak = 0

    def handler(request):
        nonlocal active, peak
        start = int(request.url.params["start"])
        if start:
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait()
            with lock:
                active -= 1
        return httpx.Response(200, json=envelope(rows[start:start+10], 50))

    assert [p.job_id for p in fetch(handler)] == [str(i+1) for i in range(50)]
    assert peak == 4


def test_remote_location_retains_country_restriction_and_shared_title_policy():
    rows = [job(1, workLocationOption="remote", locations=["United States"]),
            job(2, "Software Engineer Intern (PhD)"), job(3, "Manager, Internal Controls")]
    postings = fetch(lambda request: httpx.Response(200, json=envelope(rows)))
    assert postings[0].locations == ("Remote - United States",)
    assert classify(postings[0]).announce
    assert not classify(postings[1]).announce
    assert not classify(postings[2]).announce


@pytest.mark.parametrize("empty_first_poll", [False, True])
def test_failure_silent_recovery_new_posting_and_fallback_dedup(empty_first_poll):
    from test_main import NOW, SIMPLIFY_URL, WEBHOOKS, simplify_item

    config = Config(SIMPLIFY_URL, frozenset({"paypal"}), (BOARD,))
    state, sent = State(), []
    phase = 0

    def handler(request):
        if request.url.host == "simplify.test":
            fallback = [] if phase < 2 else [simplify_item(
                "fallback", "https://paypal.eightfold.ai/careers/job/2?utm_source=Simplify",
                company="PayPal")]
            return httpx.Response(200, json=fallback)
        if phase == 0:
            return httpx.Response(503)
        rows = ([] if empty_first_poll else [job(1)]) if phase == 1 else [job(2)]
        return httpx.Response(200, json=envelope(rows))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        def poll():
            return run(config, state, client, NOW, WEBHOOKS, save=lambda: None,
                       post=lambda client, url, content: sent.append(content))
        assert poll() == 0
        assert not state.is_board_polled(BOARD.key)
        phase = 1
        assert poll() == 0
        assert state.is_board_polled(BOARD.key)
        assert not sent
        assert len(state.records) == (0 if empty_first_poll else 1)
        phase = 2
        assert poll() == 0
        assert len(sent) == 1
        assert poll() == 0
        assert len(sent) == 1
