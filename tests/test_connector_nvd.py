import httpx

from seckb.connectors.nvd import NVDConnector
from seckb.net import build_client

NVD_JSON = {
    "resultsPerPage": 2,
    "startIndex": 0,
    "totalResults": 2,
    "vulnerabilities": [
        {
            "cve": {
                "id": "CVE-2026-0001",
                "published": "2026-09-01T00:00:00.000",
                "descriptions": [{"lang": "en", "value": "Test XSS vulnerability"}],
                "metrics": {"cvssMetricV31": [{"cvssData": {"baseScore": 9.8}}]},
                "weaknesses": [{"description": [{"value": "CWE-79"}]}],
                "references": [{"url": "https://example.com/advisory"}],
            }
        },
        {
            "cve": {
                "id": "CVE-2026-0002",
                "published": "2026-09-02T00:00:00.000",
                "descriptions": [{"lang": "en", "value": "Test RCE vulnerability"}],
                "references": [],
            }
        },
    ],
}

seen_params: list[dict] = []


def handler(request: httpx.Request) -> httpx.Response:
    seen_params.append(dict(request.url.params))
    return httpx.Response(200, json=NVD_JSON)


def test_nvd_parses_cves_and_cursor():
    client = build_client(transport=httpx.MockTransport(handler))
    # window_days=7 让 days_back=7 只形成一个窗口，聚焦解析逻辑本身
    connector = NVDConnector("nvd", client, days_back=7, window_days=7, sleep=lambda _: None)
    items, cursor = connector.fetch(None)
    assert len(items) == 2
    first = items[0]
    assert first.source_id == "CVE-2026-0001"
    assert first.asset_type == "cve"
    assert first.extra["cvss"] == 9.8
    assert first.extra["cwe"] == "CWE-79"
    assert "Test XSS vulnerability" in first.content
    assert "https://example.com/advisory" in first.content
    assert cursor and cursor.startswith("20")
    assert "lastModStartDate" in seen_params[0]


def test_nvd_uses_cursor_as_start():
    client = build_client(transport=httpx.MockTransport(handler))
    connector = NVDConnector("nvd", client, sleep=lambda _: None)
    seen_params.clear()
    connector.fetch("2026-09-01T00:00:00.000")
    assert seen_params[0]["lastModStartDate"] == "2026-09-01T00:00:00.000"


def test_nvd_sleeps_between_pages():
    page_one = {
        "resultsPerPage": 2,
        "startIndex": 0,
        "totalResults": 4,
        "vulnerabilities": NVD_JSON["vulnerabilities"],
    }
    page_two = {**page_one, "startIndex": 2}
    pages = {0: page_one, 2: page_two}

    def paged_handler(request: httpx.Request) -> httpx.Response:
        index = int(dict(request.url.params)["startIndex"])
        return httpx.Response(200, json=pages[index])

    slept: list[float] = []
    client = build_client(transport=httpx.MockTransport(paged_handler))
    connector = NVDConnector(
        "nvd",
        client,
        max_pages=5,
        page_delay=6.0,
        window_days=7,
        sleep=lambda seconds: slept.append(seconds),
    )
    items, _ = connector.fetch(None)
    assert len(items) == 4
    assert slept == [6.0]


def test_nvd_truncated_window_does_not_advance_cursor():
    """单窗口超过 max_pages*200 时，游标必须停在窗口起点，不能跳到窗口末尾。"""

    def huge_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "resultsPerPage": 200,
                "startIndex": 0,
                "totalResults": 5000,
                "vulnerabilities": [],
            },
        )

    client = build_client(transport=httpx.MockTransport(huge_handler))
    connector = NVDConnector(
        "nvd", client, max_pages=1, window_days=1, sleep=lambda _: None
    )
    _, cursor = connector.fetch("2026-09-01T00:00:00.000")
    assert cursor == "2026-09-01T00:00:00.000"


def test_nvd_multi_window_advances_by_window():
    """时间窗按 window_days 推进，游标落在已完整拉取的窗口末尾。"""

    def empty_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"resultsPerPage": 200, "startIndex": 0, "totalResults": 0, "vulnerabilities": []},
        )

    client = build_client(transport=httpx.MockTransport(empty_handler))
    connector = NVDConnector("nvd", client, window_days=1, sleep=lambda _: None)
    items, cursor = connector.fetch("2026-09-01T00:00:00.000")
    assert items == []
    assert cursor > "2026-09-01T00:00:00.000"
