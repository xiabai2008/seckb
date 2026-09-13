from seckb.indexer import fts
from seckb.search import search


def add_asset(conn, *, title: str, content: str, asset_type: str = "post") -> int:
    conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at) VALUES(?,?,?,?,?)",
        (asset_type, title, title.encode("utf-8").hex()[:16], "markdown", "now"),
    )
    asset_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO chunks(asset_id, seq, heading_path, token_count, content_md) VALUES(?,0,'',10,?)",
        (asset_id, content),
    )
    fts.index_asset(conn, asset_id)
    conn.commit()
    return asset_id


def test_chinese_substring_search(kb):
    add_asset(kb.conn, title="永恒之蓝笔记", content="MS17-010 永恒之蓝漏洞利用与防护要点")
    hits = search(kb.conn, "永恒之蓝")
    assert len(hits) == 1
    assert hits[0].title == "永恒之蓝笔记"
    assert hits[0].asset_id == 1


def test_english_search(kb):
    add_asset(kb.conn, title="sqlmap cheat", content="sqlmap tamper scripts for waf bypass")
    hits = search(kb.conn, "tamper")
    assert len(hits) == 1


def test_type_filter(kb):
    add_asset(kb.conn, title="A", content="union injection basics", asset_type="book")
    add_asset(kb.conn, title="B", content="union injection notes", asset_type="post")
    assert len(search(kb.conn, "union", asset_type="book")) == 1
    assert len(search(kb.conn, "union")) == 2


def test_short_query_returns_empty(kb):
    add_asset(kb.conn, title="A", content="waf bypass")
    assert search(kb.conn, "ab") == []


def test_rebuild(kb):
    add_asset(kb.conn, title="A", content="kubernetes escape")
    count = fts.rebuild(kb.conn)
    assert count == 1
    assert len(search(kb.conn, "kubernetes")) == 1
