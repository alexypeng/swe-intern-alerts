"""Sends messages to Discord webhooks."""

import time
from collections.abc import Callable

import httpx

MAX_RETRIES = 5


class PostError(Exception):
    pass


def send(
    client: httpx.Client,
    webhook_url: str,
    content: str,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    payload = {"content": content, "allowed_mentions": {"parse": []}}  # never ping anyone
    for _ in range(MAX_RETRIES + 1):
        try:
            # wait=true makes Discord confirm the message was created before responding.
            response = client.post(webhook_url, params={"wait": "true"}, json=payload)
        except httpx.HTTPError as e:
            # Don't include str(e): it can contain the webhook URL, which is a secret.
            raise PostError(f"request failed ({type(e).__name__})") from None
        if response.status_code == 429:
            sleep(_retry_after(response))
            continue
        if response.is_success:
            return
        raise PostError(f"Discord returned {response.status_code}: {response.text[:200]}")
    raise PostError(f"still rate limited after {MAX_RETRIES} retries")


def _retry_after(response: httpx.Response) -> float:
    try:
        return float(response.json()["retry_after"])
    except (ValueError, KeyError, TypeError):
        return float(response.headers.get("Retry-After", 1))
