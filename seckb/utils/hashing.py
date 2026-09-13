from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"spm", "from", "ref", "source", "share_token"}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    path = re.sub(r"/+", "/", parts.path) or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower() in _TRACKING_KEYS or k.lower().startswith(_TRACKING_PREFIXES))
    ]
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def slugify(title: str, max_len: int = 60) -> str:
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")
    return slug[:max_len].strip("-") or "untitled"
