"""End-to-end runs with fake HTTP for every source and for Discord."""

import json
from datetime import UTC, datetime

import httpx

from intern_alerts.config import Board, Config
from intern_alerts.main import run
from intern_alerts.models import CHANNELS
from intern_alerts.state import State

NOW = datetime(2026, 10, 4, 18, 0, tzinfo=UTC)
SIMPLIFY_URL = "https://simplify.test/listings.json"
CONFIG = Config(
    simplify_url=SIMPLIFY_URL,
    faang_plus=frozenset({"stripe"}),
    boards=(Board("greenhouse", "stripe", "Stripe"), Board("ashby", "ramp", "Ramp")),
)
WEBHOOKS = {channel: f"https://discord.test/{channel}" for channel in CHANNELS}


def gh_job(job_id, title="Software Engineer, Intern", location="Seattle, WA"):
    return {
        "id": job_id,
        "title": title,
        "location": {"name": location},
        "absolute_url": f"https://stripe.com/jobs/search?gh_jid={job_id}",
        "first_published": "2026-10-01T12:00:00-04:00",
        "updated_at": "2026-10-01T12:00:00-04:00",
    }


def ashby_job(job_id, title="Software Engineer Intern", employment="Intern"):
    return {
        "id": job_id,
        "title": title,
        "employmentType": employment,
        "location": "New York, NY",
        "secondaryLocations": [],
        "isListed": True,
        "jobUrl": f"https://jobs.ashbyhq.com/ramp/{job_id}",
        "publishedAt": "2026-10-02T00:00:00+00:00",
    }


def simplify_item(item_id, url, title="Software Engineer Intern", company="Stripe"):
    return {
        "id": item_id,
        "company_name": company,
        "title": title,
        "category": "Software",
        "active": True,
        "is_visible": True,
        "locations": ["Seattle, WA"],
        "url": url,
        "date_posted": 1788254097,
        "degrees": ["Bachelor's"],
    }


class FakeWeb:
    def __init__(self, greenhouse=(), ashby=(), simplify=()):
        self.greenhouse, self.ashby, self.simplify = list(greenhouse), list(ashby), list(simplify)
        self.fail = set()  # hosts or channels that return 500
        self.sent: dict[str, list[str]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.host == "discord.test":
            channel = request.url.path.strip("/")
            if channel in self.fail:
                return httpx.Response(500, text="boom")
            self.sent.setdefault(channel, []).append(json.loads(request.content)["content"])
            return httpx.Response(200, json={"id": "1"})
        if request.url.host in self.fail:
            return httpx.Response(500, text="down")
        if "greenhouse" in url:
            return httpx.Response(200, json={"jobs": self.greenhouse})
        if "ashbyhq" in url:
            return httpx.Response(200, json={"jobs": self.ashby})
        if url == SIMPLIFY_URL:
            return httpx.Response(200, json=self.simplify)
        return httpx.Response(404)

    def run(self, state: State, webhooks=WEBHOOKS) -> int:
        client = httpx.Client(transport=httpx.MockTransport(self.handler))
        return run(CONFIG, state, client, NOW, webhooks, save=lambda: None)


def polled_state():
    state = State()
    for key in ("greenhouse:stripe", "ashby:ramp", "simplify:faang"):
        state.mark_board_polled(key, NOW)
    return state


def test_first_run_records_silently_and_sends_nothing():
    web = FakeWeb(greenhouse=[gh_job(1)], ashby=[ashby_job("a1")])
    state = State()
    assert web.run(state) == 0
    assert web.sent == {}
    assert set(state.boards) == {"greenhouse:stripe", "ashby:ramp", "simplify:faang"}
    assert {r.job_id for r in state.records} == {"1", "a1"}


def test_second_run_announces_only_the_new_posting():
    web = FakeWeb(greenhouse=[gh_job(1)])
    state = State()
    web.run(state)
    web.greenhouse.append(gh_job(2, title="Backend Software Engineer, Intern"))
    assert web.run(state) == 0
    [message] = web.sent["swe"]
    assert "Backend Software Engineer, Intern" in message
    assert "gh_jid=1>" not in message
    assert {r.job_id for r in state.records} == {"1", "2"}

    web.sent.clear()
    web.run(state)  # third run: nothing new
    assert web.sent == {}


def test_non_matching_postings_are_neither_sent_nor_recorded():
    web = FakeWeb(
        greenhouse=[gh_job(1, title="Marketing Intern"), gh_job(2, title="Staff Engineer"),
                    gh_job(3, location="Singapore")],
        ashby=[ashby_job("a1", employment="FullTime")],
    )
    state = polled_state()
    web.run(state)
    assert web.sent == {}
    assert state.records == []


def test_failed_board_is_not_marked_polled():
    web = FakeWeb(ashby=[ashby_job("a1")])
    web.fail.add("boards-api.greenhouse.io")
    state = State()
    assert web.run(state) == 0  # a flaky source is a warning, not a failed run
    assert "greenhouse:stripe" not in state.boards
    assert "ashby:ramp" in state.boards


def test_failed_post_is_retried_next_run():
    web = FakeWeb(greenhouse=[gh_job(1)])
    web.fail.add("swe")
    state = polled_state()
    assert web.run(state) == 1
    assert state.records == []

    web.fail.clear()
    assert web.run(state) == 0
    assert len(web.sent["swe"]) == 1
    assert [r.job_id for r in state.records] == ["1"]


def test_same_job_from_board_and_simplify_in_one_run_is_sent_once():
    web = FakeWeb(
        greenhouse=[gh_job(5)],
        simplify=[simplify_item("s5", "https://stripe.com/jobs/search?gh_jid=5&utm_source=Simplify")],
    )
    state = polled_state()
    web.run(state)
    [message] = web.sent["swe"]
    assert message.count("**Stripe**") == 1
    assert len(state.records) == 1


def test_posting_in_two_channels_goes_to_both_and_is_recorded_once():
    web = FakeWeb(ashby=[ashby_job("a1", title="ML Firmware Intern")])
    state = polled_state()
    web.run(state)
    assert set(web.sent) == {"data_ml", "hardware"}
    assert len(state.records) == 1


def test_dry_run_sends_nothing(capsys):
    web = FakeWeb(greenhouse=[gh_job(1)])
    web.run(polled_state(), webhooks=None)
    assert web.sent == {}
    assert "--- swe ---" in capsys.readouterr().out
