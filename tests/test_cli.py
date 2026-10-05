"""Manual coverage checks must use the unfiltered adapter without persisting state."""
from dataclasses import replace

import httpx
import pytest

import intern_alerts.main as pipeline
from intern_alerts.config import Board, Config


@pytest.mark.parametrize("unfiltered", [False, True])
def test_dry_run_filter_override_preserves_partition_and_saves_nothing(monkeypatch, tmp_path, capfd, unfiltered):
    board = Board("workday", "nvidia/site", "NVIDIA", "nvidia.wd5.myworkdayjobs.com",
                  "jobFamilyGroup", "workerSubType", "Intern (Fixed Term)")
    config = Config("https://simplify.test/jobs", frozenset(), (board,))
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("STATE_PATH", str(state_path))
    monkeypatch.setattr(pipeline, "load_config", lambda path: config)
    monkeypatch.setattr(pipeline, "new_client", lambda: httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    ))
    fetched = []

    def fetch(client, actual):
        fetched.append(actual)
        return []

    def unexpected(*args):
        raise AssertionError("dry runs must not load webhooks or persist state")

    monkeypatch.setitem(pipeline.BOARD_FETCHERS, "workday", fetch)
    monkeypatch.setattr(pipeline, "load_webhooks", unexpected)
    monkeypatch.setattr(pipeline, "save_state", unexpected)
    assert pipeline.main(["--dry-run"] + (["--unfiltered"] if unfiltered else [])) == 0
    expected = replace(board, filter_facet=None, filter_value=None) if unfiltered else board
    assert fetched == [expected]
    assert not state_path.exists()


def test_unfiltered_requires_dry_run(capfd):
    with pytest.raises(SystemExit) as error:
        pipeline.main(["--unfiltered"])
    assert error.value.code == 2
    assert "--unfiltered requires --dry-run" in capfd.readouterr().err
