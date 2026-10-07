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
    nvidia = next(b for b in config.boards if b.key == "workday:nvidia/NVIDIAExternalCareerSite")
    assert nvidia.partition_facet == "jobFamilyGroup"
    assert nvidia.filter_facet == "workerSubType"
    assert nvidia.filter_value == "Intern (Fixed Term)"


@pytest.mark.parametrize("source,fields", [
    ("workday", 'filter_facet = "workerSubType"'),
    ("workday", 'filter_value = "Intern"'),
    ("workday", 'filter_facet = "searchText"\nfilter_value = "Intern"'),
    ("workday", 'filter_facet = "workerSubType"\nfilter_value = " "'),
    ("workday", 'filter_facet = "workerSubType"\nfilter_value = 42'),
    ("lever", 'filter_facet = "workerSubType"\nfilter_value = "Intern"'),
])
def test_invalid_native_filter_config_is_rejected(tmp_path, source, fields):
    text = ('simplify_url = "u"\nfaang_plus = []\n[[boards]]\n'
            f'source = "{source}"\nname = "NVIDIA"\nslug = "nvidia/site"\n'
            'host = "nvidia.wd5.myworkdayjobs.com"\n' + fields + '\n')
    with pytest.raises(ConfigError, match="native filter"):
        load_config(write(tmp_path, text))


def test_workday_config_rejects_unverified_partition_facet(tmp_path):
    text = ('simplify_url = "u"\nfaang_plus = []\n[[boards]]\n'
            'source = "workday"\nname = "NVIDIA"\nslug = "nvidia/site"\n'
            'host = "nvidia.wd5.myworkdayjobs.com"\npartition_facet = "searchText"\n')
    with pytest.raises(ConfigError, match="partition_facet"):
        load_config(write(tmp_path, text))


def test_faang_names_are_lowercased(tmp_path):
    config = load_config(write(tmp_path, 'simplify_url = "u"\nfaang_plus = [" Meta "]\n'))
    assert config.faang_plus == frozenset({"meta"})
    assert config.boards == ()


def test_unknown_board_source(tmp_path):
    path = write(
        tmp_path,
        'simplify_url = "u"\nfaang_plus = []\n'
        '[[boards]]\nsource = "unknown"\nslug = "x"\nname = "X"\n',
    )
    with pytest.raises(ConfigError, match="unknown source"):
        load_config(path)


def test_board_missing_field(tmp_path):
    path = write(tmp_path, 'simplify_url = "u"\nfaang_plus = []\n[[boards]]\nsource = "ashby"\n')
    with pytest.raises(ConfigError, match="board #1 is missing"):
        load_config(path)


@pytest.mark.parametrize("host,slug", [
    ("", "salesforce/Futureforce_Internships"),
    ("example.com", "salesforce/Futureforce_Internships"),
    ("salesforce.wd12.myworkdayjobs.com", "other/Futureforce_Internships"),
    ("salesforce.wd12.myworkdayjobs.com", "salesforce/site/extra"),
])
def test_workday_config_rejects_invalid_board_address(tmp_path, host, slug):
    text = ('simplify_url = "u"\nfaang_plus = []\n[[boards]]\n'
            f'source = "workday"\nname = "Salesforce"\nhost = "{host}"\nslug = "{slug}"\n')
    with pytest.raises(ConfigError, match="Workday board requires"):
        load_config(write(tmp_path, text))


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


@pytest.mark.parametrize('source,name', [('meta', 'Meta'), ('amazon', 'Amazon')])
def test_custom_board_config(tmp_path, source, name):
    text = ('simplify_url = "u"\nfaang_plus = []\n[[boards]]\n'
            f'source = "{source}"\nslug = "{source}"\nname = "{name}"\n')
    assert load_config(write(tmp_path, text)).boards[0].key == f'{source}:{source}'
    for change in ('slug = "other"', 'name = "Other"', 'host = "example.com"',
                   'partition_facet = "jobFamilyGroup"'):
        lines = text.splitlines()
        key = change.split(' = ')[0]
        modified = '\n'.join(line for line in lines if not line.startswith(key + ' = '))
        with pytest.raises(ConfigError, match=f'{name} board requires'):
            load_config(write(tmp_path, modified + '\n' + change + '\n'))
