from seckb.pipeline.importer import scan_inbox
from seckb.search import search


def test_full_pipeline(kb):
    inbox = kb.root / "inbox"
    (inbox / "one.md").write_text(
        "# 永恒之蓝复现\n\n使用 nmap 探测 445 端口，MS17-010 永恒之蓝可 getshell。\n\n"
        "```bash\nnmap -sV -p445 10.0.0.1\n```\n",
        encoding="utf-8",
    )
    (inbox / "two.html").write_text(
        "<html><head><title>XSS 绕过 WAF</title></head><body>"
        "<p>利用大小写混淆与注释分割绕过 waf 对 onerror 的拦截。</p></body></html>",
        encoding="utf-8",
    )
    reports = scan_inbox(kb.conn, kb.settings)
    assert all(r.status == "imported" for r in reports)

    hits = search(kb.conn, "永恒之蓝")
    assert hits and hits[0].asset_id == 1

    posts = list((kb.root / "posts").rglob("*.md"))
    assert len(posts) == 2

    snippet = kb.conn.execute("SELECT COUNT(*) FROM snippets").fetchone()[0]
    assert snippet >= 1
