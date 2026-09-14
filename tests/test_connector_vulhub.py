import httpx

from seckb.connectors.vulhub import VulhubConnector
from seckb.net import build_client

TREE_JSON = {
    "tree": [
        {"path": ".github", "type": "tree"},
        {"path": ".github/workflows", "type": "tree"},
        {"path": "fastjson", "type": "tree"},
        {"path": "fastjson/1.2.24-rce", "type": "tree"},
        {"path": "fastjson/1.2.24-rce/docker-compose.yml", "type": "blob"},
        {"path": "fastjson/1.2.24-rce/README.md", "type": "blob"},
        {"path": "log4j", "type": "tree"},
        {"path": "log4j/CVE-2021-44228/docker-compose.yml", "type": "blob"},
    ]
}


def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=TREE_JSON)


def test_vulhub_environments():
    client = build_client(transport=httpx.MockTransport(handler))
    items, _ = VulhubConnector("vulhub", client, sleep=lambda _: None).fetch(None)
    ids = sorted(i.source_id for i in items)
    assert ids == ["vulhub:1.2.24-rce", "vulhub:CVE-2021-44228"]
    fastjson = next(i for i in items if i.source_id == "vulhub:1.2.24-rce")
    assert fastjson.asset_type == "writeup"
    assert "docker-compose.yml" in fastjson.content
    assert "https://github.com/vulhub/vulhub/tree/master/fastjson/1.2.24-rce" in fastjson.content
