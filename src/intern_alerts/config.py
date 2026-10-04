"""Loads config.toml and the per-channel webhook secrets."""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from intern_alerts.models import CHANNELS

BOARD_SOURCES = ("greenhouse", "ashby")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Board:
    source: str  # "greenhouse" or "ashby"
    slug: str  # the board ID in the source's API URL
    name: str  # display name, also the company name used for dedup

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
            board = Board(source=raw["source"], slug=raw["slug"], name=raw["name"])
        except KeyError as e:
            raise ConfigError(f"{path}: board #{i + 1} is missing {e}") from None
        if board.source not in BOARD_SOURCES:
            raise ConfigError(
                f"{path}: board {board.slug!r} has unknown source {board.source!r} "
                f"(expected one of {', '.join(BOARD_SOURCES)})"
            )
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
