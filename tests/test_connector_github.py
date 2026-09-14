import httpx

from seckb.connectors.github import GitHubConnector
from seckb.net import build_client

SEARCH_JSON = {
    "items": [
        {
            "full_name": "owner/tool",
            "html_url": "https://github.com/owner/tool",
            "description": "A security tool",
            "stargazers_count": 1200,
            "forks_count": 100,
            "language": "Go",
            "topics": ["security", "scanner"],
            "clone_url": "https://github.com/owner/tool.git",
            "license": {"spdx_id": "MIT"},
            "archived": False,
            "pushed_at": "2026-09-01T00:00:00Z",
        }
    ]
}

README = """
# Awesome Security
- [tool](https://github.com/owner/tool)
- [another](https://github.com/owner/another)
- [self](https://github.com/awesome/list)
"""


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "/search/repositories" in url:
        return httpx.Response(200, json=SEARCH_JSON)
    if url.endswith("/README.md"):
        return httpx.Response(200, text=README)
    return httpx.Response(404, text="not found")


def make_connector():
    client = build_client(transport=httpx.MockTransport(handler))
    return GitHubConnector(
        "github",
        client,
        queries=["topic:security stars:>1000"],
        awesome_repos=["awesome/list"],
        sleep=lambda _: None,
    )


def test_github_search_items():
    items, cursor = make_connector().fetch(None)
    search_items = [i for i in items if i.source_id == "repo:owner/tool"]
    assert len(search_items) == 1
    item = search_items[0]
    assert item.asset_type == "repo"
    assert item.extra["stars"] == 1200
    assert item.extra["license"] == "MIT"
    assert item.extra["topics"] == ["security", "scanner"]
    assert cursor is None


def test_github_awesome_links_deduped_and_self_excluded():
    items, _ = make_connector().fetch(None)
    awesome_ids = sorted(i.source_id for i in items if i.source_id.startswith("awesome:"))
    assert awesome_ids == ["awesome:owner/another", "awesome:owner/tool"]
