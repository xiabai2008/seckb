from __future__ import annotations

import time
from collections.abc import Callable

import httpx

USER_AGENT = "seckb/0.2 (+local knowledge base)"
RETRY_STATUS = {429, 500, 502, 503, 504}
BACKOFF_BASE = 0.5


class FetchError(Exception):
    pass


def build_client(
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 20.0,
    headers: dict | None = None,
) -> httpx.Client:
    merged = {"User-Agent": USER_AGENT}
    if headers:
        merged.update(headers)
    return httpx.Client(
        timeout=timeout, headers=merged, transport=transport, follow_redirects=True
    )


def _request(
    client: httpx.Client,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url, params=params, headers=headers)
            if response.status_code in RETRY_STATUS and attempt < attempts:
                sleep(BACKOFF_BASE * 2**attempt)
                continue
            if response.status_code >= 400:
                raise FetchError(f"GET {url} -> HTTP {response.status_code}")
            return response
        except httpx.TransportError as exc:
            last_error = exc
            if attempt < attempts:
                sleep(BACKOFF_BASE * 2**attempt)
                continue
            raise FetchError(f"GET {url} failed: {exc}") from exc
    raise FetchError(f"GET {url} retries exhausted: {last_error}")


def fetch_json(
    client: httpx.Client,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    return _request(
        client, url, params=params, headers=headers, attempts=attempts, sleep=sleep
    ).json()


def fetch_text(
    client: httpx.Client,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    return _request(
        client, url, params=params, headers=headers, attempts=attempts, sleep=sleep
    ).text


def fetch_bytes(
    client: httpx.Client,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    return _request(
        client, url, params=params, headers=headers, attempts=attempts, sleep=sleep
    ).content
