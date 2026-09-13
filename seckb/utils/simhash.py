from __future__ import annotations

import hashlib
import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _hash64(token: str) -> int:
    return int.from_bytes(hashlib.md5(token.encode("utf-8")).digest()[:8], "big")


def simhash64(text: str, shingle: int = 3) -> int:
    tokens = _tokens(text)
    if not tokens:
        return 0
    if len(tokens) < shingle:
        grams = [" ".join(tokens)]
    else:
        grams = [" ".join(tokens[i : i + shingle]) for i in range(len(tokens) - shingle + 1)]
    counts: dict[str, int] = {}
    for gram in grams:
        counts[gram] = counts.get(gram, 0) + 1
    vector = [0] * 64
    for gram, weight in counts.items():
        h = _hash64(gram)
        for i in range(64):
            vector[i] += weight if (h >> i) & 1 else -weight
    out = 0
    for i in range(64):
        if vector[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def to_signed64(h: int) -> int:
    return h - (1 << 64) if h >= (1 << 63) else h


def from_signed64(h: int) -> int:
    return h + (1 << 64) if h < 0 else h
