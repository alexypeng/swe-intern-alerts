import json

import httpx
import pytest

from intern_alerts.post import MAX_RETRIES, PostError, send

WEBHOOK = "https://discord.test/api/webhooks/123/secret-token"


def client_with(responses, requests):
    queue = list(responses)

    def handler(request):
        requests.append(request)
        return queue.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_sends_content_without_mentions():
    requests = []
    send(client_with([httpx.Response(200, json={"id": "1"})], requests), WEBHOOK, "hello")
    [request] = requests
    assert request.url.params["wait"] == "true"
    assert json.loads(request.content) == {"content": "hello", "allowed_mentions": {"parse": []}}


def test_retries_after_rate_limit():
    requests, sleeps = [], []
    responses = [
        httpx.Response(429, json={"retry_after": 1.5}),
        httpx.Response(200, json={"id": "1"}),
    ]
    send(client_with(responses, requests), WEBHOOK, "hi", sleep=sleeps.append)
    assert sleeps == [1.5]
    assert len(requests) == 2


def test_gives_up_after_max_retries():
    responses = [httpx.Response(429, json={"retry_after": 0})] * (MAX_RETRIES + 1)
    with pytest.raises(PostError, match="still rate limited"):
        send(client_with(responses, []), WEBHOOK, "hi", sleep=lambda s: None)


def test_other_errors_raise_without_leaking_webhook_url():
    with pytest.raises(PostError, match="404") as e:
        send(client_with([httpx.Response(404, text="Unknown Webhook")], []), WEBHOOK, "hi")
    assert "secret-token" not in str(e.value)


def test_network_error_does_not_leak_webhook_url():
    def handler(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(PostError) as e:
        send(client, WEBHOOK, "hi")
    assert "secret-token" not in str(e.value)
