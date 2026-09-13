from pathlib import Path

from seckb.pipeline.normalize import html_to_markdown


def test_html_to_markdown_extracts_title_and_strips_scripts(tmp_path: Path):
    html = """
    <html><head><title>SQL 注入实战</title>
    <script>alert(1)</script><style>p{color:red}</style></head>
    <body><h1>SQL 注入实战</h1>
    <p>这是第一段内容，讲述 union 注入的基本原理与利用方式。</p>
    <p>这是第二段内容，给出防护建议与修复方案，供读者参考实践。</p>
    </body></html>
    """
    title, md = html_to_markdown(html, base_dir=tmp_path, images_dir=None)
    assert title == "SQL 注入实战"
    assert "# SQL 注入实战" in md
    assert "<script>" not in md
    assert "union 注入" in md


def test_html_images_localized_with_injected_fetcher(tmp_path: Path):
    html = """
    <html><head><title>PoC 展示</title></head><body>
    <p>下面给出一个可用于验证漏洞的截图，说明请求与响应之间的差异。</p>
    <img src="https://example.com/poc.png" alt="poc">
    <p>该截图展示了未授权访问成功返回敏感数据的完整过程与细节。</p>
    </body></html>
    """
    calls: list[str] = []

    def fake_fetcher(url: str) -> bytes:
        calls.append(url)
        return b"\x89PNG fake-bytes"

    title, md = html_to_markdown(
        html, base_dir=tmp_path, images_dir=tmp_path / "PoC.assets", fetcher=fake_fetcher
    )
    assert calls == ["https://example.com/poc.png"]
    assert (tmp_path / "PoC.assets" / "img-1.png").exists()
    assert "PoC.assets/img-1.png" in md
