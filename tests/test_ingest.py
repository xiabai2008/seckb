from pathlib import Path

from seckb.connectors.base import RawItem
from seckb.pipeline.entities import link_entity
from seckb.pipeline.importer import import_file
from seckb.pipeline.ingest import ingest_items


def test_link_entity_reuses_entity(kb):
    kb.conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at) VALUES('post','t','x1','markdown','now')"
    )
    kb.conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at) VALUES('post','t2','x2','markdown','now')"
    )
    a = link_entity(kb.conn, 1, "tool", "nmap")
    b = link_entity(kb.conn, 2, "tool", "NMAP")
    assert a == b


def test_import_records_source_metadata(kb, tmp_path: Path):
    src = tmp_path / "n.md"
    src.write_text("# 测试源元数据\n\n内容。", encoding="utf-8")
    report = import_file(
        kb.conn,
        kb.settings,
        src,
        source="rss",
        source_url="https://example.com/post/1",
        published_at="2026-09-01T08:00:00",
        source_id="https://example.com/post/1",
    )
    row = kb.conn.execute("SELECT * FROM assets WHERE id = ?", (report.asset_id,)).fetchone()
    assert row["source"] == "rss"
    assert row["source_url"] == "https://example.com/post/1"
    assert row["published_at"] == "2026-09-01T08:00:00"
    assert row["source_id"] == "https://example.com/post/1"


def test_import_routes_repo_and_cve(kb, tmp_path: Path):
    repo_src = tmp_path / "repo.md"
    repo_src.write_text("# owner/name\n\n一个安全工具仓库。", encoding="utf-8")
    report = import_file(
        kb.conn,
        kb.settings,
        repo_src,
        asset_type="repo",
        source="github",
        source_id="repo:owner/name",
        extra={"owner": "owner", "name": "name", "stars": 1200, "topics": ["security"]},
    )
    row = kb.conn.execute("SELECT * FROM assets WHERE id = ?", (report.asset_id,)).fetchone()
    assert row["path"].startswith("repos/")
    repo_row = kb.conn.execute(
        "SELECT * FROM repos WHERE asset_id = ?", (report.asset_id,)
    ).fetchone()
    assert repo_row["stars"] == 1200

    cve_src = tmp_path / "cve.md"
    cve_src.write_text("# CVE-2026-0001\n\n测试漏洞。", encoding="utf-8")
    report2 = import_file(
        kb.conn,
        kb.settings,
        cve_src,
        asset_type="cve",
        source="nvd",
        source_id="CVE-2026-0001",
        published_at="2026-08-20T00:00:00.000",
        extra={"cvss": 9.8, "cwe": "CWE-79", "poc_refs": ["https://example.com/poc"]},
    )
    row2 = kb.conn.execute("SELECT * FROM assets WHERE id = ?", (report2.asset_id,)).fetchone()
    assert row2["path"].startswith("vulndb/2026/")
    cve_row = kb.conn.execute(
        "SELECT * FROM cves WHERE asset_id = ?", (report2.asset_id,)
    ).fetchone()
    assert cve_row["cvss"] == 9.8
    assert cve_row["in_kev"] == 0


def test_ingest_creates_asset_and_job(kb):
    items = [
        RawItem(
            source_id="https://example.com/a",
            title="测试帖子",
            content="这是来自 RSS 的正文，包含 nmap 关键词。",
            url="https://example.com/a",
            published_at="2026-09-02T00:00:00",
        )
    ]
    stats = ingest_items(kb.conn, kb.settings, items, source="rss")
    assert stats.imported == 1
    row = kb.conn.execute(
        "SELECT * FROM assets WHERE source_id = 'https://example.com/a'"
    ).fetchone()
    assert row["source"] == "rss"
    job = kb.conn.execute("SELECT * FROM jobs WHERE asset_id = ?", (row["id"],)).fetchone()
    assert job["kind"] == "summary"
    assert job["status"] == "pending"


def test_ingest_dedupes_by_source_id(kb):
    item = RawItem(source_id="dup-1", title="重复", content="内容。", url=None)
    assert ingest_items(kb.conn, kb.settings, [item], source="rss").imported == 1
    assert ingest_items(kb.conn, kb.settings, [item], source="rss").skipped == 1
    count = kb.conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    assert count == 1


def test_ingest_marks_existing_cve_in_kev(kb):
    src_path = kb.root / "meta" / "tmp" / "cve-seed.md"
    src_path.parent.mkdir(parents=True, exist_ok=True)
    src_path.write_text("# CVE-2021-44228\n\nLog4Shell。", encoding="utf-8")
    report = import_file(
        kb.conn,
        kb.settings,
        src_path,
        asset_type="cve",
        source="nvd",
        source_id="CVE-2021-44228",
    )
    kev_item = RawItem(
        source_id="CVE-2021-44228",
        title="CVE-2021-44228 KEV",
        content="在野利用。",
        asset_type="cve",
        extra={"in_kev": True, "cve_id": "CVE-2021-44228"},
    )
    stats = ingest_items(kb.conn, kb.settings, [kev_item], source="kev")
    assert stats.updated == 1
    assert stats.imported == 0
    row = kb.conn.execute(
        "SELECT * FROM cves WHERE asset_id = ?", (report.asset_id,)
    ).fetchone()
    assert row["in_kev"] == 1
