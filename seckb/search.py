from __future__ import annotations

import sqlite3

from seckb.indexer.fts import SearchHit, search as fts_search


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    asset_type: str | None = None,
    limit: int = 10,
) -> list[SearchHit]:
    return fts_search(conn, query, asset_type=asset_type, limit=limit)
