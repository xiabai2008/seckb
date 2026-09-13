from __future__ import annotations

import re

from seckb.models import ChunkDraft
from seckb.utils.tokens import estimate_tokens

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_PARA_SPLIT_RE = re.compile(r"\n{2,}")


def _split_sections(md: str) -> list[tuple[list[str], str]]:
    sections: list[tuple[list[str], str]] = []
    stack: list[tuple[int, str]] = []
    current_path: list[str] = []
    current_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((list(current_path), body))

    for line in md.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            flush()
            current_lines = []
            level = len(match.group(1))
            stack = [(lvl, text) for lvl, text in stack if lvl < level]
            stack.append((level, match.group(2).strip()))
            current_path = [text for _, text in stack]
            current_lines.append(line)
        else:
            current_lines.append(line)
    flush()
    return sections


def _hard_split(text: str, max_tokens: int) -> list[str]:
    total = estimate_tokens(text)
    approx_chars = max(1, int(len(text) * max_tokens / total))
    return [text[i : i + approx_chars] for i in range(0, len(text), approx_chars)]


def _split_long(text: str, target_tokens: int, max_tokens: int) -> list[str]:
    paragraphs = [p for p in _PARA_SPLIT_RE.split(text) if p.strip()]
    blocks: list[str] = []
    buffer: list[str] = []
    for paragraph in paragraphs:
        buffer.append(paragraph)
        if estimate_tokens("\n\n".join(buffer)) >= target_tokens:
            blocks.append("\n\n".join(buffer))
            buffer = []
    if buffer:
        blocks.append("\n\n".join(buffer))
    out: list[str] = []
    for block in blocks:
        if estimate_tokens(block) <= max_tokens:
            out.append(block)
        else:
            out.extend(_hard_split(block, max_tokens))
    return out


def _tail(text: str, overlap_tokens: int) -> str:
    paragraphs = [p for p in _PARA_SPLIT_RE.split(text) if p.strip()]
    tail: list[str] = []
    for paragraph in reversed(paragraphs):
        candidate = "\n\n".join([paragraph, *reversed(tail)])
        if tail and estimate_tokens(candidate) > overlap_tokens:
            break
        tail.append(paragraph)
    return "\n\n".join(reversed(tail))


def chunk_markdown(
    md: str,
    *,
    target_tokens: int = 700,
    max_tokens: int = 1000,
    overlap_tokens: int = 80,
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    seq = 0
    for path, body in _split_sections(md):
        pieces = _split_long(body, target_tokens, max_tokens) if estimate_tokens(body) > max_tokens else [body]
        previous_tail = ""
        for piece in pieces:
            content = piece
            if previous_tail:
                candidate = previous_tail + "\n\n" + piece
                if estimate_tokens(candidate) <= max_tokens:
                    content = candidate
            drafts.append(
                ChunkDraft(
                    seq=seq,
                    heading_path=" > ".join(path),
                    content=content,
                    token_count=estimate_tokens(content),
                )
            )
            seq += 1
            previous_tail = _tail(piece, overlap_tokens)
    return drafts
