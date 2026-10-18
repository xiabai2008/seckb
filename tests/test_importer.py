from pathlib import Path

from seckb.pipeline.importer import import_file, scan_inbox


def write_post(tmp_path: Path, name: str = "post.md", body: str = "") -> Path:
    text = body or (
        "# 永恒之蓝利用笔记\n\n"
        "MS17-010 永恒之蓝漏洞，使用 nmap 扫描后利用 msf 模块 getshell。\n\n"
        "```bash\nnmap -sV -p445 10.0.0.1\n```\n"
    )
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_import_markdown_post(kb, tmp_path: Path):
    src = write_post(tmp_path)
    report = import_file(kb.conn, kb.settings, src)
    assert report.status == "imported"
    row = kb.conn.execute("SELECT * FROM assets WHERE id = ?", (report.asset_id,)).fetchone()
    assert row["type"] == "post"
    assert row["lang"] == "zh"
    assert row["path"] == row["md_path"]
    assert "永恒之蓝" in row["title"]
    assert src.exists()
    md_files = list((kb.root / "posts" / "zh").glob("*.md"))
    assert len(md_files) == 1


def test_import_markdown_deletes_tmp_with_env(kb, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SECKB_DELETE_TMP", "1")
    src = write_post(tmp_path)
    report = import_file(kb.conn, kb.settings, src)
    assert report.status == "imported"
    assert not src.exists()


def test_import_creates_chunks_and_snippets(kb, tmp_path: Path):
    report = import_file(kb.conn, kb.settings, write_post(tmp_path))
    chunk_count = kb.conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE asset_id = ?", (report.asset_id,)
    ).fetchone()[0]
    snippet = kb.conn.execute(
        "SELECT * FROM snippets WHERE asset_id = ?", (report.asset_id,)
    ).fetchone()
    assert chunk_count >= 1
    assert snippet["kind"] == "oneliner"
    assert "nmap -sV" in snippet["content"]


def test_import_links_entities(kb, tmp_path: Path):
    report = import_file(kb.conn, kb.settings, write_post(tmp_path))
    rows = kb.conn.execute(
        """SELECT e.kind, e.name FROM asset_entities ae
           JOIN entities e ON e.id = ae.entity_id WHERE ae.asset_id = ?""",
        (report.asset_id,),
    ).fetchall()
    pairs = {(row["kind"], row["name"]) for row in rows}
    assert ("tool", "nmap") in pairs


def test_duplicate_by_sha256(kb, tmp_path: Path):
    src_a = write_post(tmp_path, "a.md")
    first = import_file(kb.conn, kb.settings, src_a)
    src_b = write_post(tmp_path, "b.md")
    second = import_file(kb.conn, kb.settings, src_b)
    assert second.status == "duplicated"
    assert second.asset_id == first.asset_id
    assert src_b.exists()


def test_scanned_pdf_needs_ocr(kb, tmp_path: Path):
    import pymupdf

    blank = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(blank))
    doc.close()
    report = import_file(kb.conn, kb.settings, blank)
    assert report.status == "needs_ocr"
    assert blank.exists()


def test_scan_inbox(kb, tmp_path: Path):
    write_post(kb.root / "inbox", "one.md", "# 提权笔记\n\nlinux 提权常见手法：suid、sudo、cron。")
    write_post(kb.root / "inbox", "two.md", "# XSS 笔记\n\n反射型 xss 的利用与绕过，配合 csrf 链式利用。")
    reports = scan_inbox(kb.conn, kb.settings)
    assert [r.status for r in reports] == ["imported", "imported"]
    again = scan_inbox(kb.conn, kb.settings)
    assert [r.status for r in again] == ["duplicated", "duplicated"]


def test_book_gets_sidecar_meta(kb, tmp_path: Path):
    import pymupdf

    pdf = tmp_path / "handbook.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Web Security Handbook")
    page.insert_text((72, 96), "Chapter 1: xss and sql injection basics")
    doc.save(str(pdf))
    doc.close()
    report = import_file(kb.conn, kb.settings, pdf)
    assert report.status == "imported"
    row = kb.conn.execute("SELECT * FROM assets WHERE id = ?", (report.asset_id,)).fetchone()
    assert row["type"] == "book"
    assert row["category"] == "web-security"
    meta_files = list((kb.root / "books" / "web-security").glob("*.meta.json"))
    assert len(meta_files) == 1
