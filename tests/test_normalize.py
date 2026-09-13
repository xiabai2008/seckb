from pathlib import Path

import pymupdf
from ebooklib import epub

from seckb.pipeline.normalize import (
    ScannedPdfError,
    epub_to_markdown,
    html_to_markdown,
    normalize_to_markdown,
    pdf_to_markdown,
)


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

    _title, md = html_to_markdown(
        html, base_dir=tmp_path, images_dir=tmp_path / "PoC.assets", fetcher=fake_fetcher
    )
    assert calls == ["https://example.com/poc.png"]
    assert (tmp_path / "PoC.assets" / "img-1.png").exists()
    assert "PoC.assets/img-1.png" in md


def make_text_pdf(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "SQL Injection Handbook")
    page.insert_text((72, 96), "Chapter 1: UNION based injection basics")
    doc.save(str(path))
    doc.close()


def test_pdf_to_markdown_extracts_text(tmp_path: Path):
    pdf_path = tmp_path / "book.pdf"
    make_text_pdf(pdf_path)
    _title, md = pdf_to_markdown(pdf_path)
    assert "UNION based injection" in md


def test_scanned_pdf_raises(tmp_path: Path):
    blank = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(blank))
    doc.close()
    try:
        pdf_to_markdown(blank)
    except ScannedPdfError:
        pass
    else:
        raise AssertionError("expected ScannedPdfError")


def test_epub_to_markdown(tmp_path: Path):
    epub_path = tmp_path / "notes.epub"
    book = epub.EpubBook()
    book.set_identifier("test-1")
    book.set_title("Crypto Notes")
    book.set_language("en")
    chapter = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
    chapter.content = (
        "<html><body><h1>Chapter 1</h1><p>Caesar cipher and frequency analysis.</p></body></html>"
    )
    book.add_item(chapter)
    book.toc = (chapter,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(epub_path), book)

    title, md = epub_to_markdown(epub_path)
    assert title == "Crypto Notes"
    assert "Caesar cipher" in md


def test_normalize_dispatch_markdown_passthrough(tmp_path: Path):
    src = tmp_path / "note.md"
    src.write_text("# 提权笔记\n\nLinux 提权常用方法汇总", encoding="utf-8")
    result = normalize_to_markdown(src, out_dir=tmp_path / "out", stem="s1")
    assert result.source_type == "markdown"
    assert result.title == "note"
    assert "提权笔记" in result.markdown
    assert result.needs_ocr is False


def test_normalize_dispatch_html(tmp_path: Path):
    src = tmp_path / "post.html"
    src.write_text(
        "<html><head><title>xss 利用</title></head>"
        "<body><p>反射型 xss 的基本利用链与绕过思路说明。</p></body></html>",
        encoding="utf-8",
    )
    result = normalize_to_markdown(src, out_dir=tmp_path / "out", stem="s2")
    assert result.source_type == "html"
    assert result.title == "xss 利用"
