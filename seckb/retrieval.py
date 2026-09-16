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


def build_retriever(conn: sqlite3.Connection, settings: Settings) -> "HybridRetriever":
    from seckb.indexer.meili import build_meili_client
    from seckb.indexer.vectors import build_embedder

    try:
        meili = build_meili_client(settings.enrich)
    except Exception:  # noqa: BLE001 - 索引客户端不可用时降级为关键词检索
        meili = None
    try:
        embedder = build_embedder(settings.enrich)
    except Exception:  # noqa: BLE001 - 嵌入不可用时降级为关键词检索
        embedder = None
    return HybridRetriever(conn, settings, meili=meili, embedder=embedder)


class HybridRetriever:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        meili=None,
        embedder=None,
    ) -> None:
        self.conn = conn
        self.settings = settings
        self.meili = meili
        self.embedder = embedder

    def _pools(
        self, query: str, candidate_limit: int, asset_type: str | None
    ) -> tuple[list[tuple[str, list[Candidate]]], list[str]]:
        pools: list[tuple[str, list[Candidate]]] = []
        degraded: list[str] = []
        fts_hits = fts.search(self.conn, query, limit=candidate_limit, asset_type=asset_type)
        pools.append(
            ("fts", [Candidate(hit.asset_id, hit.chunk_id, rank) for rank, hit in enumerate(fts_hits, 1)])
        )
        if self.meili is not None:
            try:
                filters = f'type = "{asset_type}"' if asset_type else None
                meili_hits = self.meili.search(query, limit=candidate_limit, filters=filters)
                pools.append(
                    (
                        "meili",
                        [
                            Candidate(int(hit["id"]), None, rank)
                            for rank, hit in enumerate(meili_hits, 1)
                        ],
                    )
                )
            except Exception:  # noqa: BLE001 - 单路失败降级并记录
                degraded.append("meili")
        if self.embedder is not None:
            try:
                vector_hits = search_vectors(
                    self.settings, self.embedder, query, limit=candidate_limit
                )
                pools.append(
                    (
                        "vector",
                        [
                            Candidate(hit.asset_id, hit.chunk_id, rank)
                            for rank, hit in enumerate(vector_hits, 1)
                        ],
                    )
                )
            except Exception:  # noqa: BLE001 - 单路失败降级并记录
                degraded.append("vector")
        return pools, degraded

    def _build_result(self, fused: FusedCandidate) -> SearchResult | None:
        row = self.conn.execute(
            """
            SELECT a.*, c.summary AS card_summary
            FROM assets a LEFT JOIN cards c ON c.asset_id = a.id
            WHERE a.id = ?
            """,
            (fused.asset_id,),
        ).fetchone()
        if row is None:
            return None
        snippet = _snippet(self.conn, fused.chunk_id)
        summary = row["card_summary"] or ""
        return SearchResult(
            asset_id=fused.asset_id,
            title=row["title"],
            type=row["type"],
            lang=row["lang"],
            tags=json.loads(row["tags"] or "[]"),
            category=row["category"],
            source=row["source"],
            source_url=row["source_url"],
            published_at=row["published_at"],
            summary=summary,
            snippet=snippet,
            matched_by=sorted(fused.matched_by),
            score=round(fused.score, 6),
            token_estimate=estimate_tokens(snippet) + estimate_tokens(summary) + 20,
        )

    def search(
        self,
        query: str,
        *,
        asset_type: str | None = None,
        tag: str | None = None,
        limit: int = 10,
    ) -> SearchResponse:
        candidate_limit = max(limit * 3, 20)
        pools, degraded = self._pools(query, candidate_limit, asset_type)
        fused_list = rrf_fuse(pools)
        results: list[SearchResult] = []
        for fused in fused_list:
            result = self._build_result(fused)
            if result is None:
                continue
            if asset_type and result.type != asset_type:
                continue
            if tag and tag not in result.tags:
                continue
            results.append(result)
            if len(results) >= limit:
                break
        return SearchResponse(results=results, degraded=degraded)
