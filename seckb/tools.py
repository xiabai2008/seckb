from __future__ import annotations

import json
import sqlite3

from seckb.retrieval import HybridRetriever, SearchResult


def _result_to_dict(result: SearchResult) -> dict:
    return {
        "asset_id": result.asset_id,
        "title": result.title,
        "type": result.type,
        "lang": result.lang,
        "tags": result.tags,
        "category": result.category,
        "source": result.source,
        "source_url": result.source_url,
        "published_at": result.published_at,
        "summary": result.summary,
        "snippet": result.snippet,
        "matched_by": result.matched_by,
        "score": result.score,
        "token_estimate": result.token_estimate,
    }


def kb_search(
    conn: sqlite3.Connection,
    retriever: HybridRetriever,
    query: str,
    *,
    type: str | None = None,
    tag: str | None = None,
    limit: int = 8,
) -> dict:
    response = retriever.search(query, asset_type=type, tag=tag, limit=limit)
    results = [_result_to_dict(item) for item in response.results]
    return {
        "query": query,
        "results": results,
        "degraded": response.degraded,
        "token_estimate": sum(item["token_estimate"] for item in results) + 50,
    }


def kb_card(conn: sqlite3.Connection, asset_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT a.title, a.type, a.lang, a.tags, a.category, a.source, a.source_url,
               a.published_at, c.summary, c.key_takeaways, c.card_json, c.model, c.generated_at
        FROM assets a LEFT JOIN cards c ON c.asset_id = a.id
        WHERE a.id = ?
        """,
        (asset_id,),
    ).fetchone()
    if row is None:
        return None
    card_json = {}
    if row["card_json"]:
        try:
            card_json = json.loads(row["card_json"])
        except json.JSONDecodeError:
            card_json = {}
    return {
        "asset_id": asset_id,
        "title": row["title"],
        "type": row["type"],
        "lang": row["lang"],
        "tags": json.loads(row["tags"] or "[]"),
        "category": row["category"],
        "source": row["source"],
        "source_url": row["source_url"],
        "published_at": row["published_at"],
        "has_card": row["summary"] is not None,
        "summary": row["summary"] or "",
        "key_takeaways": json.loads(row["key_takeaways"] or "[]"),
        "entities": card_json.get("entities", {}),
        "model": row["model"],
        "generated_at": row["generated_at"],
    }
