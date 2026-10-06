"""Loads config.toml and the per-channel webhook secrets."""

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from intern_alerts.models import CHANNELS

BOARD_SOURCES = ("greenhouse", "ashby", "lever", "smartrecruiters", "workday", "meta")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Board:
    source: str  # one of BOARD_SOURCES
    slug: str  # the board ID in the source's API URL
    name: str  # display name, also the company name used for dedup
    host: str | None = None  # Workday: <tenant>.wd<number>.myworkdayjobs.com
    partition_facet: str | None = None  # verified Workday large-board partition
    filter_facet: str | None = None  # native Workday filter, validated per board
    filter_value: str | None = None  # display label; resolve its ID each poll

    @property
    def key(self) -> str:
        return f"{self.source}:{self.slug}"


@dataclass(frozen=True)
class Config:
    simplify_url: str
    faang_plus: frozenset[str]  # lowercase company names
    boards: tuple[Board, ...]


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        data = tomllib.load(f)

    try:
        simplify_url = data["simplify_url"]
        faang_plus = frozenset(name.strip().lower() for name in data["faang_plus"])
        raw_boards = data.get("boards", [])
    except KeyError as e:
        raise ConfigError(f"{path}: missing required key {e}") from None

    boards = []
    seen_keys = set()
    for i, raw in enumerate(raw_boards):
        try:
            board = Board(source=raw["source"], slug=raw["slug"], name=raw["name"],
                          host=raw.get("host"), partition_facet=raw.get("partition_facet"),
                          filter_facet=raw.get("filter_facet"), filter_value=raw.get("filter_value"))
        except KeyError as e:
            raise ConfigError(f"{path}: board #{i + 1} is missing {e}") from None
        if board.source not in BOARD_SOURCES:
            raise ConfigError(
                f"{path}: board {board.slug!r} has unknown source {board.source!r} "
                f"(expected one of {', '.join(BOARD_SOURCES)})"
            )
        if board.source == "meta" and (board.slug != "meta" or board.name != "Meta"
                                       or board.host is not None or board.partition_facet is not None):
            raise ConfigError(f"{path}: Meta board requires slug 'meta', name 'Meta', and no host/partition")
        if board.filter_facet is not None or board.filter_value is not None:
            if (board.source != "workday"
                    or board.filter_facet not in ("workerSubType", "jobFamilyGroup")
                    or not isinstance(board.filter_value, str) or not board.filter_value.strip()):
                raise ConfigError(f"{path}: native filter requires a Workday filter_facet "
                                  "(workerSubType or jobFamilyGroup) and nonempty filter_value")
        if board.source == "workday":
            if not isinstance(board.host, str) or not isinstance(board.slug, str):
                raise ConfigError(f"{path}: Workday board requires a matching host and tenant/site slug")
            host = re.fullmatch(r"([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com", board.host or "")
            slug = re.fullmatch(r"([a-z0-9-]+)/([A-Za-z0-9_-]+)", board.slug)
            if not host or not slug or host[1] != slug[1]:
                raise ConfigError(f"{path}: Workday board requires a matching host and tenant/site slug")
            if board.partition_facet not in (None, "jobFamilyGroup"):
                raise ConfigError(f"{path}: unsupported Workday partition_facet")
        if board.key in seen_keys:
            raise ConfigError(f"{path}: board {board.key!r} is listed twice")
        seen_keys.add(board.key)
        boards.append(board)

    return Config(simplify_url=simplify_url, faang_plus=faang_plus, boards=tuple(boards))


def webhook_env_name(channel: str) -> str:
    return f"WEBHOOK_{channel.upper()}"


def load_webhooks(env: Mapping[str, str] = os.environ) -> dict[str, str]:
    """Returns {channel: webhook URL}. Raises if any channel's secret is missing."""
    missing = [webhook_env_name(c) for c in CHANNELS if not env.get(webhook_env_name(c))]
    if missing:
        raise ConfigError(f"Missing webhook secrets: {', '.join(missing)}")
    return {c: env[webhook_env_name(c)] for c in CHANNELS}
