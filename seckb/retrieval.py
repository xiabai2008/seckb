from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

from seckb.config import Settings
from seckb.indexer import fts
from seckb.indexer.vectors import search_vectors
from seckb.utils.tokens import estimate_tokens

RRF_K = 60
SNIPPET_LIMIT = 200


@dataclass
class Candidate:
    asset_id: int
    chunk_id: int | None
    rank: int


@dataclass
class FusedCandidate:
    asset_id: int
    score: float
    chunk_id: int | None
    matched_by: set[str] = field(default_factory=set)


@dataclass
class SearchResult:
    asset_id: int
    title: str
    type: str
    lang: str
    tags: list[str]
    category: str | None
    source: str
    source_url: str | None
    published_at: str | None
    summary: str
    snippet: str
    matched_by: list[str]
    score: float
    token_estimate: int


@dataclass
class SearchResponse:
    results: list[SearchResult]
    degraded: list[str] = field(default_factory=list)


def rrf_fuse(pools: list[tuple[str, list[Candidate]]], *, k: int = RRF_K) -> list[FusedCandidate]:
    scores: dict[int, float] = {}
    matched: dict[int, set[str]] = {}
    chunks: dict[int, int | None] = {}
    for name, candidates in pools:
        for candidate in candidates:
            scores[candidate.asset_id] = scores.get(candidate.asset_id, 0.0) + 1.0 / (
                k + candidate.rank
            )
            matched.setdefault(candidate.asset_id, set()).add(name)
            if candidate.asset_id not in chunks:
                chunks[candidate.asset_id] = candidate.chunk_id
    fused = [
        FusedCandidate(
            asset_id=asset_id,
            score=score,
            chunk_id=chunks[asset_id],
            matched_by=matched[asset_id],
        )
        for asset_id, score in scores.items()
    ]
    fused.sort(key=lambda item: (-item.score, item.asset_id))
    return fused


def _snippet(conn: sqlite3.Connection, chunk_id: int | None) -> str:
    if chunk_id is None:
        return ""
    row = conn.execute(
        "SELECT heading_path, content_md FROM chunks WHERE id = ?", (chunk_id,)
    ).fetchone()
    if row is None:
        return ""
    body = re.sub(r"\s+", " ", row["content_md"]).strip()
    heading = (row["heading_path"] or "").strip()
    text = f"{heading}: {body}" if heading else body
    return text[:SNIPPET_LIMIT]
