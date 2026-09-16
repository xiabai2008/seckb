import httpx

from seckb.connectors.github_docs import GitHubDocsConnector
from seckb.net import build_client

TREE_JSON = {
    "tree": [
        {"path": "README.md", "type": "blob"},
        {"path": ".github/workflows/ci.yml", "type": "blob"},
        {"path": "src/alpha.md", "type": "blob"},
        {"path": "src/beta.markdown", "type": "blob"},
        {"path": "src/todo/wip.md", "type": "blob"},
        {"path": "docs/gamma.md", "type": "blob"},
        {"path": "src/data.json", "type": "blob"},
    ]
}

BODIES = {
    "src/alpha.md": "# Alpha 技术\n\n利用方式说明。",
    "src/beta.markdown": "# Beta 技术\n\n验证步骤。",
}


def make_handler(tree=TREE_JSON, bodies=None):
    bodies = bodies if bodies is not None else BODIES

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.github.com" in url and "/git/trees/" in url:
            return httpx.Response(200, json=tree)
        if "raw.githubusercontent.com" in url:
            path = url.split("/HEAD/", 1)[-1]
            from urllib.parse import unquote

            path = unquote(path)
            if path in bodies:
                return httpx.Response(200, text=bodies[path])
            return httpx.Response(404, text="missing")
        return httpx.Response(404, text="not found")

    return handler


def test_github_docs_filters_and_caps():
    client = build_client(transport=httpx.MockTransport(make_handler()))
    connector = GitHubDocsConnector(
        "github_docs",
        client,
        repos=[
            {
                "repo": "owner/kb",
                "include_prefixes": ["src/"],
                "exclude_prefixes": ["src/todo/"],
                "max_files": 2,
            }
        ],
        sleep=lambda _: None,
    )
    items, cursor = connector.fetch(None)
    assert [item.source_id for item in items] == ["owner/kb/src/alpha.md", "owner/kb/src/beta.markdown"]
    first = items[0]
    assert first.title == "alpha"
    assert first.url == "https://github.com/owner/kb/blob/HEAD/src/alpha.md"
    assert "# Alpha 技术" in first.content
    assert first.extra["site"] == "https://github.com/owner/kb"
    assert cursor is None


def test_github_docs_extensionless_files():
    tree = {
        "tree": [
            {"path": "_gtfobins/7z", "type": "blob"},
            {"path": "_gtfobins/R", "type": "blob"},
            {"path": "README.md", "type": "blob"},
        ]
    }
    bodies = {"_gtfobins/7z": "---\nfunctions:\n  shell:\n", "_gtfobins/R": "---\nfunctions:\n"}
    client = build_client(transport=httpx.MockTransport(make_handler(tree, bodies)))
    connector = GitHubDocsConnector(
        "github_docs",
        client,
        repos=[
            {
                "repo": "GTFOBins/GTFOBins.github.io",
                "include_prefixes": ["_gtfobins/"],
                "suffixes": [""],
                "title_prefix": "GTFOBins",
            }
        ],
        sleep=lambda _: None,
    )
    items, _ = connector.fetch(None)
    assert [item.source_id for item in items] == [
        "GTFOBins/GTFOBins.github.io/_gtfobins/7z",
        "GTFOBins/GTFOBins.github.io/_gtfobins/R",
    ]
    assert items[0].title == "GTFOBins 7z"


def test_github_docs_skips_failed_downloads():
    tree = {"tree": [{"path": "src/ok.md", "type": "blob"}, {"path": "src/missing.md", "type": "blob"}]}
    bodies = {"src/ok.md": "# 可用\n\n内容。"}
    client = build_client(transport=httpx.MockTransport(make_handler(tree, bodies)))
    connector = GitHubDocsConnector(
        "github_docs",
        client,
        repos=[{"repo": "owner/kb"}],
        sleep=lambda _: None,
    )
    items, _ = connector.fetch(None)
    assert [item.source_id for item in items] == ["owner/kb/src/ok.md"]
