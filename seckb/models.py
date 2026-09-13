from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Asset:
    type: str
    title: str
    sha256: str
    format: str
    size: int = 0
    lang: str = "zh"
    source: str = "manual"
    source_url: str | None = None
    path: str | None = None
    md_path: str | None = None
    simhash: int | None = None
    published_at: str | None = None
    tags: list[str] = field(default_factory=list)
    category: str | None = None
    status: str = "ok"


@dataclass
class ChunkDraft:
    seq: int
    heading_path: str
    content: str
    token_count: int


@dataclass
class SnippetDraft:
    kind: str
    lang: str | None
    content: str
    context: str = ""
    tool: str | None = None
