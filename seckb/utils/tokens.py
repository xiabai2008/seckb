from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_NON_TEXT_RE = re.compile(r"[^\w\s\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    words = len(_WORD_RE.findall(text))
    punctuation = len(_NON_TEXT_RE.findall(text))
    return cjk + words + punctuation // 4
