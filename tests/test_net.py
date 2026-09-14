import httpx
import pytest

from seckb.net import FetchError, build_client, fetch_json


def test_fetch_json_retries_transport_error():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json={"ok": True})

    client = build_client(transport=httpx.MockTransport(handler))
    data = fetch_json(client, "https://example.com/api", sleep=lambda _: None)
    assert data == {"ok": True}
    assert len(calls) == 2


def test_fetch_json_retries_503_then_success():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"n": len(calls)})

    client = build_client(transport=httpx.MockTransport(handler))
    assert fetch_json(client, "https://example.com/x", sleep=lambda _: None) == {"n": 2}


def test_fetch_json_raises_after_attempts():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("always down")

    client = build_client(transport=httpx.MockTransport(handler))
    with pytest.raises(FetchError):
        fetch_json(client, "https://example.com/y", attempts=3, sleep=lambda _: None)


def test_fetch_json_http_400_is_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="nope")

    client = build_client(transport=httpx.MockTransport(handler))
    with pytest.raises(FetchError):
        fetch_json(client, "https://example.com/z", sleep=lambda _: None)
