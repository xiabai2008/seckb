from __future__ import annotations

import ipaddress
import re
import socket
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from markdownify import markdownify
from readability import Document

Fetcher = Callable[[str], bytes]

_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_ALLOWED_IMG_SCHEMES = frozenset({"http", "https"})


class ScannedPdfError(Exception):
    pass


class BlockedImageError(ValueError):
    """图片地址被安全策略拒绝（非公网 http(s) 地址）。"""


def _ensure_public_url(url: str) -> None:
    """抓图前校验：只允许指向公网主机的 http(s) 地址。

    图片链接来自被采集的第三方页面，属不可信输入，不加限制就等于把采集器
    变成内网探测工具。域名解析后逐个校验解析结果，避免 DNS 指向内网。
    """
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_IMG_SCHEMES:
        raise BlockedImageError(f"仅允许 http/https 图片地址，收到: {parts.scheme or '(无协议)'}")
    host = parts.hostname
    if not host:
        raise BlockedImageError("图片地址缺少主机名")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise BlockedImageError(f"图片地址无法解析: {host}") from exc
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError as exc:
            raise BlockedImageError(f"图片地址解析结果异常: {info[4][0]}") from exc
        if not ip.is_global or ip.is_multicast:
            raise BlockedImageError(f"图片地址解析到非公网地址: {ip}")


class _PublicOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """重定向也要过公网校验，否则公网 URL 可以 302 到内网。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _ensure_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_PUBLIC_OPENER = urllib.request.build_opener(_PublicOnlyRedirectHandler)


def _default_fetcher(url: str) -> bytes:
    _ensure_public_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "seckb/0.1"})
    with _PUBLIC_OPENER.open(request, timeout=20) as response:
        return response.read()


def _read_image(src: str, base_dir: Path | None, fetcher: Fetcher) -> tuple[bytes | None, str]:
    if src.startswith(("http://", "https://")):
        try:
            data = fetcher(src)
        except BlockedImageError:
            return None, ""  # 单张图片被拒不应中断整篇入库
        suffix = Path(urlsplit(src).path).suffix.lower() or ".img"
        return data, suffix
    if base_dir is not None:
        local = (base_dir / src).resolve()
        if local.is_file():
            return local.read_bytes(), local.suffix.lower() or ".img"
    return None, ""


def _localize_images(
    md: str,
    *,
    base_dir: Path | None,
    images_dir: Path,
    fetcher: Fetcher,
) -> str:
    images_dir.mkdir(parents=True, exist_ok=True)
    counter = 0

    def repl(match: re.Match) -> str:
        nonlocal counter
        alt, src = match.group(1), match.group(2)
        data, suffix = _read_image(src, base_dir, fetcher)
        if data is None:
            return match.group(0)
        counter += 1
        name = f"img-{counter}{suffix}"
        (images_dir / name).write_bytes(data)
        return f"![{alt}]({images_dir.name}/{name})"

    return _IMG_RE.sub(repl, md)


def html_to_markdown(
    html: str,
    *,
    base_dir: Path | None = None,
    images_dir: Path | None = None,
    fetcher: Fetcher | None = None,
) -> tuple[str, str]:
    doc = Document(html)
    title = (doc.title() or "").strip()
    body_html = doc.summary(html_partial=True)
    md = markdownify(body_html, heading_style="ATX", strip=["script", "style"])
    if images_dir is not None:
        md = _localize_images(
            md, base_dir=base_dir, images_dir=images_dir, fetcher=fetcher or _default_fetcher
        )
    return title, md.strip() + "\n"


_EXT_FORMAT = {
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".pdf": "pdf",
    ".epub": "epub",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "markdown",
}

_PDF_MIN_CHARS_PER_PAGE = 30


class NormalizeResult:
    __slots__ = ("markdown", "needs_ocr", "source_type", "title")

    def __init__(self, title: str, markdown: str, source_type: str, needs_ocr: bool = False):
        self.title = title
        self.markdown = markdown
        self.source_type = source_type
        self.needs_ocr = needs_ocr


def guess_format(path: Path) -> str:
    return _EXT_FORMAT.get(path.suffix.lower(), "markdown")


def pdf_to_markdown(path: Path) -> tuple[str, str]:
    import pymupdf
    import pymupdf4llm

    doc = pymupdf.open(str(path))
    pages = doc.page_count
    text_len = sum(len(page.get_text()) for page in doc)
    if pages > 0 and text_len / pages < _PDF_MIN_CHARS_PER_PAGE:
        doc.close()
        raise ScannedPdfError(f"{path.name}: 疑似扫描版，需 OCR")
    title = (doc.metadata or {}).get("title") or ""
    md = pymupdf4llm.to_markdown(str(path))
    doc.close()
    return title.strip(), md.strip() + "\n"


def epub_to_markdown(path: Path) -> tuple[str, str]:
    from ebooklib import ITEM_DOCUMENT, epub

    book = epub.read_epub(str(path))
    title = ""
    metadata = book.get_metadata("DC", "title")
    if metadata:
        title = str(metadata[0][0])
    parts: list[str] = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        html = item.get_content().decode("utf-8", errors="replace")
        _, md = html_to_markdown(html)
        if md.strip():
            parts.append(md.strip())
    return title.strip(), "\n\n".join(parts) + "\n"


def normalize_to_markdown(
    src: Path,
    *,
    out_dir: Path,
    stem: str,
    fetcher: Fetcher | None = None,
) -> NormalizeResult:
    fmt = guess_format(src)
    if fmt == "html":
        html = src.read_text(encoding="utf-8", errors="replace")
        images_dir = out_dir / f"{stem}.assets" if _IMG_RE.search(html) else None
        title, md = html_to_markdown(
            html, base_dir=src.parent, images_dir=images_dir, fetcher=fetcher
        )
        return NormalizeResult(title or src.stem, md, "html")
    if fmt == "pdf":
        try:
            title, md = pdf_to_markdown(src)
        except ScannedPdfError:
            return NormalizeResult(src.stem, "", "pdf", needs_ocr=True)
        return NormalizeResult(title or src.stem, md, "pdf")
    if fmt == "epub":
        title, md = epub_to_markdown(src)
        return NormalizeResult(title or src.stem, md, "epub")
    md = src.read_text(encoding="utf-8", errors="replace")
    return NormalizeResult(src.stem, md.strip() + "\n", "markdown")
