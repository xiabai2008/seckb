from __future__ import annotations

import re
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from markdownify import markdownify
from readability import Document

Fetcher = Callable[[str], bytes]

_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


class ScannedPdfError(Exception):
    pass


def _default_fetcher(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "seckb/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def _read_image(src: str, base_dir: Path | None, fetcher: Fetcher) -> tuple[bytes | None, str]:
    if src.startswith(("http://", "https://")):
        data = fetcher(src)
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
