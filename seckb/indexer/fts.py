from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

_INTERNAL_QUOTE = re.compile(r'"')


@dataclass
class SearchHit:
    asset_id: int
    chunk_id: int
    title: str
    heading_path: str
    snippet: str
    score: float


def build_query(raw: str) -> str:
    terms = [t for t in re.split(r"\s+", raw.strip()) if len(t) >= 3]
    if not terms:
        return ""
    return " AND ".join('"' + _INTERNAL_QUOTE.sub('""', t) + '"' for t in terms)


def index_asset(conn: sqlite3.Connection, asset_id: int) -> None:
    conn.execute(
        """
        INSERT INTO chunks_fts(rowid, content, heading_path, asset_id)
        SELECT c.id, c.content_md, c.heading_path, c.asset_id
        FROM chunks c WHERE c.asset_id = ?
        """,
        (asset_id,),
    )


def rebuild(conn: sqlite3.Connection) -> int:
    conn.execute("DELETE FROM chunks_fts")
    conn.execute(
        """
        INSERT INTO chunks_fts(rowid, content, heading_path, asset_id)
        SELECT c.id, c.content_md, c.heading_path, c.asset_id FROM chunks c
        """
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]


def _search(
    conn: sqlite3.Connection,
    match: str,
    *,
    limit: int,
    asset_type: str | None,
) -> list[SearchHit]:
    sql = """
        SELECT f.asset_id, f.rowid AS chunk_id, a.title, f.heading_path,
               snippet(chunks_fts, 0, '[', ']', '…', 16) AS snip,
               bm25(chunks_fts, 10.0, 1.0) AS score
        FROM chunks_fts f
        JOIN assets a ON a.id = f.asset_id
        WHERE chunks_fts MATCH ?
    """
    params: list = [match]
    if asset_type:
        sql += " AND a.type = ?"
        params.append(asset_type)
    sql += " ORDER BY score LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [
        SearchHit(
            asset_id=row["asset_id"],
            chunk_id=row["chunk_id"],
            title=row["title"],
            heading_path=row["heading_path"] or "",
            snippet=row["snip"] or "",
            score=float(row["score"]),
        )
        for row in rows
    ]


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 10,
    asset_type: str | None = None,
) -> list[SearchHit]:
    match = build_query(query)
    if not match:
        return []
    return _search(conn, match, limit=limit, asset_type=asset_type)


def build_query_any(terms: list[str]) -> str:
    parts = [
        '"' + _INTERNAL_QUOTE.sub('""', term) + '"' for term in terms if len(term) >= 3
    ]
    return " OR ".join(parts)


def search_any(
    conn: sqlite3.Connection,
    terms: list[str],
    *,
    limit: int = 10,
    asset_type: str | None = None,
) -> list[SearchHit]:
    match = build_query_any(terms)
    if not match:
        return []
    return _search(conn, match, limit=limit, asset_type=asset_type)
