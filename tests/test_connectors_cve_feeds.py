import httpx

from seckb.connectors.exploitdb import ExploitDBConnector
from seckb.connectors.kev import KEVConnector
from seckb.net import build_client

KEV_JSON = {
    "vulnerabilities": [
        {
            "cveID": "CVE-2021-44228",
            "vendorProject": "Apache",
            "product": "Log4j",
            "vulnerabilityName": "Log4Shell",
            "dateAdded": "2021-12-10",
            "shortDescription": "Remote code execution in Log4j.",
            "requiredAction": "Apply updates.",
        }
    ]
}

CSV_TEXT = (
    "id,file,description,date_published,author,type,platform,date_added,date_updated,"
    "verified,codes,tags,aliases,screenshot_url,application_url,source_url\n"
    "50001,exploits/a.py,Old Exploit,2020-01-01,alice,remote,linux,2020-01-02,2020-01-03,"
    "1,CVE-2020-1111,,,,\n"
    "50003,exploits/c.py,Newest Exploit,2026-01-01,bob,local,linux,2026-01-02,2026-01-03,"
    "1,CVE-2026-2222;OSVDB-1,,,,\n"
    "50002,exploits/b.py,Middle Exploit,2023-01-01,carol,webapps,php,2023-01-02,2023-01-03,"
    "0,,, ,,,\n"
)


def kev_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=KEV_JSON)


def csv_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=CSV_TEXT)


def test_kev_parses_entries():
    client = build_client(transport=httpx.MockTransport(kev_handler))
    items, cursor = KEVConnector("kev", client, sleep=lambda _: None).fetch(None)
    assert len(items) == 1
    item = items[0]
    assert item.source_id == "CVE-2021-44228"
    assert item.extra["in_kev"] is True
    assert "Log4Shell" in item.content
    assert cursor is None


def test_exploitdb_sorted_and_limited():
    client = build_client(transport=httpx.MockTransport(csv_handler))
    connector = ExploitDBConnector("exploitdb", client, max_rows=2, sleep=lambda _: None)
    items, _ = connector.fetch(None)
    assert [i.source_id for i in items] == ["EDB-50003", "EDB-50002"]
    assert items[0].asset_type == "cve"
    assert items[0].extra["cve_id"] == "CVE-2026-2222"
    assert "https://www.exploit-db.com/exploits/50003" in items[0].content
