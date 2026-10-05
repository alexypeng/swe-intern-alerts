"""Runs one poll: fetch, classify, dedup, post to Discord, save state."""

import argparse
import os
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

import httpx

from intern_alerts.classify import classify
from intern_alerts.config import Config, ConfigError, load_config, load_webhooks
from intern_alerts.dedup import SeenIndex
from intern_alerts.format import build_messages
from intern_alerts.models import CHANNELS, Posting
from intern_alerts.post import PostError, send
from intern_alerts.sources import SourceError, new_client
from intern_alerts.sources.ashby import fetch_ashby
from intern_alerts.sources.greenhouse import fetch_greenhouse
from intern_alerts.sources.lever import fetch_lever
from intern_alerts.sources.simplify import board_key as simplify_board_key
from intern_alerts.sources.simplify import fetch_simplify
from intern_alerts.sources.smartrecruiters import fetch_smartrecruiters
from intern_alerts.sources.workday import fetch_workday
from intern_alerts.state import Record, State, StateError, load_state, save_state

BOARD_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "ashby": fetch_ashby,
    "lever": fetch_lever,
    "smartrecruiters": fetch_smartrecruiters,
    "workday": fetch_workday,
}
BOARD_WORKERS = 4


def fetch_all(
    client: httpx.Client, config: Config
) -> list[tuple[str, set[str], list[Posting]]]:
    """Fetches boards concurrently in config order, then Simplify; omits failed sources.

    Returns (label, board keys the fetch covered, postings) for each successful fetch.
    A fetch covers a board even if it returned no postings for it.
    """
    jobs: list[tuple[str, set[str], Callable[[], list[Posting]]]] = [
        (board.key, {board.key}, lambda board=board: BOARD_FETCHERS[board.source](client, board))
        for board in config.boards
    ]
    simplify = (
        "simplify",
        {simplify_board_key(name) for name in config.faang_plus},
        lambda: fetch_simplify(client, config.simplify_url, config.faang_plus),
    )

    def fetch_timed(job):
        label, keys, fetch = job
        started = perf_counter()
        try:
            postings = fetch()
        except SourceError as e:
            return label, keys, None, str(e), perf_counter() - started
        return label, keys, postings, None, perf_counter() - started

    fetched = []

    def collect(result):
        label, keys, postings, error, elapsed = result
        if error is not None:
            print(f"::warning::skipped {error}")
        else:
            fetched.append((label, keys, postings))
        print(f"fetch {label}: {elapsed:.2f}s ({'failed' if error else 'ok'})")

    started = perf_counter()
    # map yields in input order even when requests finish out of order. Only
    # network fetching touches workers; run() processes all state sequentially.
    with ThreadPoolExecutor(max_workers=BOARD_WORKERS) as pool:
        for result in pool.map(fetch_timed, jobs):
            collect(result)
    collect(fetch_timed(simplify))
    print(f"fetch total: {perf_counter() - started:.2f}s")
    return fetched


def run(
    config: Config,
    state: State,
    client: httpx.Client,
    now: datetime,
    webhooks: dict[str, str] | None,  # None means dry run: print instead of sending
    save: Callable[[], None],
    post: Callable[[httpx.Client, str, str], None] = send,
    backfill_since: datetime | None = None,  # first-poll postings newer than this are sent
) -> int:
    pruned = state.prune(now)
    if pruned:
        print(f"pruned {pruned} records older than a year")

    index = SeenIndex(state.records)
    queue: dict[str, list[tuple[Posting, frozenset[str]]]] = defaultdict(list)
    skipped: Counter[str] = Counter()
    unrecognized: Counter[str] = Counter()

    for label, board_keys, postings in fetch_all(client, config):
        first_poll_keys = {key for key in board_keys if not state.is_board_polled(key)}
        new = silent = 0
        for posting in postings:
            result = classify(posting)
            unrecognized.update(result.unrecognized)
            if not result.announce:
                continue
            reason = index.seen_by(posting)
            if reason:
                skipped[reason] += 1
                continue
            index.add(Record.from_posting(posting))
            backfill = backfill_since is not None and posting.posted_at >= backfill_since
            if posting.board_key in first_poll_keys and not backfill:
                state.record(posting, now)  # silent: existing postings are never announced
                silent += 1
            else:
                new += 1
                for channel in result.channels:
                    queue[channel].append((posting, result.regions))
        for key in board_keys:
            state.mark_board_polled(key, now)
        first = f", {len(first_poll_keys)} first-polled" if first_poll_keys else ""
        print(f"{label}: {len(postings)} fetched, {new} new, {silent} recorded silently{first}")

    save()  # keep silent records even if posting fails below

    failures = 0
    recorded: set[Posting] = set()
    for channel in CHANNELS:
        if not queue[channel]:
            continue
        messages = build_messages(queue[channel])
        sent = 0
        for message in messages:
            if webhooks is None:
                print(f"--- {channel} ---\n{message.content}")
            else:
                try:
                    post(client, webhooks[channel], message.content)
                except PostError as e:
                    # Unsent postings stay unrecorded, so the next run retries them.
                    print(f"::error::{channel}: {e}")
                    failures += 1
                    break
            for posting in message.postings:
                if posting not in recorded:
                    recorded.add(posting)
                    state.record(posting, now)
            save()
            sent += 1
        print(f"{channel}: sent {sent}/{len(messages)} messages, {len(queue[channel])} postings")

    if skipped:
        print("skipped as already seen: " + ", ".join(f"{k}={v}" for k, v in sorted(skipped.items())))
    if unrecognized:
        print("unrecognized locations: " + ", ".join(sorted(unrecognized)))
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # emoji and accents on Windows consoles

    parser = argparse.ArgumentParser(prog="intern_alerts", description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print messages instead of sending them; don't save state")
    parser.add_argument("--backfill", type=int, metavar="DAYS",
                        help="one-off: send every open posting from the last DAYS days, "
                             "ignoring and not saving state (running it twice sends twice)")
    parser.add_argument("--config", default="config.toml", type=Path)
    args = parser.parse_args(argv)

    state_path = Path(os.environ.get("STATE_PATH", "state.json"))
    now = datetime.now(UTC)
    persist = not (args.dry_run or args.backfill)
    try:
        config = load_config(args.config)
        webhooks = None if args.dry_run else load_webhooks()
        state = State() if args.backfill else load_state(state_path)
    except (ConfigError, StateError) as e:
        print(f"::error::{e}")
        return 1

    def save() -> None:
        if persist:
            save_state(state, state_path)

    backfill_since = now - timedelta(days=args.backfill) if args.backfill else None
    with new_client() as client:
        return run(config, state, client, now, webhooks, save, backfill_since=backfill_since)
