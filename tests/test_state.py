import json
from datetime import UTC, datetime, timedelta

import pytest

from intern_alerts.models import Posting
from intern_alerts.state import State, StateError, load_state, save_state

NOW = datetime(2026, 10, 4, 18, 0, tzinfo=UTC)


def posting(job_id="8128745", url="https://stripe.com/jobs/search?gh_jid=8128745&utm_source=x"):
    return Posting(
        source="greenhouse",
        board_key="greenhouse:stripe",
        job_id=job_id,
        company="Stripe",
        title="Software Engineer, Intern",
        locations=("Seattle, WA", "NYC"),
        url=url,
        posted_at=NOW,
    )


def test_missing_file_is_empty_state(tmp_path):
    state = load_state(tmp_path / "state.json")
    assert state.boards == {}
    assert state.records == []
    assert not state.is_board_polled("greenhouse:stripe")


def test_round_trip(tmp_path):
    path = tmp_path / "state.json"
    state = State()
    state.mark_board_polled("greenhouse:stripe", NOW)
    state.record(posting(), NOW)
    save_state(state, path)

    loaded = load_state(path)
    assert loaded == state
    assert loaded.is_board_polled("greenhouse:stripe")
    assert not (tmp_path / "state.json.tmp").exists()


def test_record_stores_normalized_fields():
    record = State().record(posting(), NOW)
    assert record.company == "stripe"
    assert record.job_id == "8128745"
    assert record.url == "https://stripe.com/jobs/search?gh_jid=8128745"
    assert record.title == "software engineer intern"
    assert record.location == "nyc; seattle wa"
    assert record.first_seen == "2026-10-04T18:00:00Z"


def test_mark_board_polled_keeps_first_time():
    state = State()
    state.mark_board_polled("ashby:ramp", NOW)
    state.mark_board_polled("ashby:ramp", NOW + timedelta(hours=1))
    assert state.boards["ashby:ramp"] == "2026-10-04T18:00:00Z"


def test_prune_drops_records_older_than_a_year():
    state = State()
    state.record(posting("old"), NOW - timedelta(days=366))
    state.record(posting("edge"), NOW - timedelta(days=365))
    state.record(posting("new"), NOW)
    assert state.prune(NOW) == 1
    assert [r.job_id for r in state.records] == ["edge", "new"]


def test_corrupt_file_is_an_error_not_a_reset(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StateError, match="unreadable"):
        load_state(path)


def test_wrong_version_is_an_error(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"version": 99, "boards": {}, "postings": []}), encoding="utf-8")
    with pytest.raises(StateError, match="unsupported version"):
        load_state(path)
