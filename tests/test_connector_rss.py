import httpx

from seckb.connectors.rss import RSSConnector
from seckb.net import build_client

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>安全资讯</title>
<item>
  <title>Nmap 使用技巧</title>
  <link>https://example.com/nmap</link>
  <guid>https://example.com/nmap</guid>
  <pubDate>Mon, 01 Sep 2026 08:00:00 GMT</pubDate>
  <description>&lt;p&gt;使用 &lt;b&gt;nmap&lt;/b&gt; 扫描端口&lt;/p&gt;</description>
</item>
<item>
  <title>SQLMap 进阶</title>
  <link>https://example.com/sqlmap</link>
  <guid>https://example.com/sqlmap</guid>
  <description>sqlmap tamper 脚本说明</description>
</item>
</channel></rss>
"""


def test_rss_connector_parses_entries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=FEED, headers={"Content-Type": "application/rss+xml"})

    client = build_client(transport=httpx.MockTransport(handler))
    connector = RSSConnector("rss", ["https://example.com/feed"], client, sleep=lambda _: None)
    items, cursor = connector.fetch(None)
    assert len(items) == 2
    first = items[0]
    assert first.source_id == "https://example.com/nmap"
    assert first.title == "Nmap 使用技巧"
    assert "nmap" in first.content
    assert "<p>" not in first.content
    assert first.published_at is not None
    assert cursor is None
