from pathlib import Path

import pytest

from intern_alerts.config import ConfigError, load_config, load_webhooks

REPO_CONFIG = Path(__file__).parent.parent / "config.toml"

ALL_WEBHOOKS = {
    "WEBHOOK_SWE": "https://discord.test/swe",
    "WEBHOOK_DATA_ML": "https://discord.test/data_ml",
    "WEBHOOK_HARDWARE": "https://discord.test/hardware",
    "WEBHOOK_QUANT": "https://discord.test/quant",
    "WEBHOOK_OTHER_ENG": "https://discord.test/other_eng",
    "WEBHOOK_PRODUCT": "https://discord.test/product",
}


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_repo_config_loads():
    config = load_config(REPO_CONFIG)
    assert "stripe" in config.faang_plus
    assert {b.key for b in config.boards} >= {"greenhouse:stripe", "ashby:ramp"}


def test_faang_names_are_lowercased(tmp_path):
    config = load_config(write(tmp_path, 'simplify_url = "u"\nfaang_plus = [" Meta "]\n'))
    assert config.faang_plus == frozenset({"meta"})
    assert config.boards == ()


def test_unknown_board_source(tmp_path):
    path = write(
        tmp_path,
        'simplify_url = "u"\nfaang_plus = []\n'
        '[[boards]]\nsource = "lever"\nslug = "x"\nname = "X"\n',
    )
    with pytest.raises(ConfigError, match="unknown source"):
        load_config(path)


def test_board_missing_field(tmp_path):
    path = write(tmp_path, 'simplify_url = "u"\nfaang_plus = []\n[[boards]]\nsource = "ashby"\n')
    with pytest.raises(ConfigError, match="board #1 is missing"):
        load_config(path)


def test_duplicate_board(tmp_path):
    board = '[[boards]]\nsource = "ashby"\nslug = "ramp"\nname = "Ramp"\n'
    path = write(tmp_path, 'simplify_url = "u"\nfaang_plus = []\n' + board + board)
    with pytest.raises(ConfigError, match="listed twice"):
        load_config(path)


def test_webhooks_all_present():
    webhooks = load_webhooks(ALL_WEBHOOKS)
    assert webhooks["data_ml"] == "https://discord.test/data_ml"
    assert len(webhooks) == 6


def test_webhooks_missing_names_each_missing_secret():
    env = {k: v for k, v in ALL_WEBHOOKS.items() if k not in ("WEBHOOK_QUANT", "WEBHOOK_PRODUCT")}
    with pytest.raises(ConfigError, match="WEBHOOK_QUANT, WEBHOOK_PRODUCT"):
        load_webhooks(env)
