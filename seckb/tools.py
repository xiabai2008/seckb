from __future__ import annotations

import json
import sqlite3

from seckb.retrieval import HybridRetriever, SearchResult
from seckb.utils.tokens import estimate_tokens


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
               a.published_at, c.summary, c.key_takeaways, c.card_json, c.model, c.generated_at,
               v.cve_id AS cve_cve_id, v.cvss AS cve_cvss, v.cwe AS cve_cwe,
               v.poc_refs AS cve_poc_refs, v.in_kev AS cve_in_kev
        FROM assets a
        LEFT JOIN cards c ON c.asset_id = a.id
        LEFT JOIN cves v ON v.asset_id = a.id
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
    cve = None
    if row["type"] == "cve":
        cve = {
            "cve_id": row["cve_cve_id"],
            "cvss": row["cve_cvss"],
            "cwe": row["cve_cwe"],
            "in_kev": bool(row["cve_in_kev"]),
            "poc_refs": json.loads(row["cve_poc_refs"] or "[]"),
        }
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
        "cve": cve,
        "model": row["model"],
        "generated_at": row["generated_at"],
    }


def kb_get(
    conn: sqlite3.Connection,
    asset_id: int,
    *,
    section: str | None = None,
    max_tokens: int = 2000,
) -> dict | None:
    asset = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if asset is None:
        return None
    rows = conn.execute(
        "SELECT heading_path, content_md FROM chunks WHERE asset_id = ? ORDER BY seq",
        (asset_id,),
    ).fetchall()
    sections: list[str] = []
    for row in rows:
        heading = (row["heading_path"] or "").strip()
        if heading and heading not in sections:
            sections.append(heading)
    if section:
        needle = section.lower()
        rows = [row for row in rows if needle in (row["heading_path"] or "").lower()]
    parts: list[str] = []
    total = 0
    truncated = False
    for row in rows:
        heading = (row["heading_path"] or "").strip()
        block = f"[{heading}]\n{row['content_md']}" if heading else row["content_md"]
        block_tokens = estimate_tokens(block)
        if total + block_tokens > max_tokens:
            truncated = True
            break
        parts.append(block)
        total += block_tokens
    if len(parts) < len(rows):
        truncated = True
    content = "\n\n".join(parts)
    return {
        "asset_id": asset_id,
        "title": asset["title"],
        "type": asset["type"],
        "source": asset["source"],
        "source_url": asset["source_url"],
        "path": asset["path"],
        "content": content,
        "sections": sections,
        "truncated": truncated,
        "token_estimate": estimate_tokens(content) + 20,
    }


def kb_snippets(
    conn: sqlite3.Connection,
    *,
    query: str | None = None,
    tool: str | None = None,
    kind: str | None = None,
    limit: int = 10,
) -> dict:
    conditions: list[str] = []
    params: list = []
    if tool:
        conditions.append("s.tool = ?")
        params.append(tool)
    if kind:
        conditions.append("s.kind = ?")
        params.append(kind)
    if query:
        conditions.append("s.content LIKE ?")
        params.append(f"%{query}%")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"""
        SELECT s.asset_id, a.title, s.kind, s.lang, s.tool, s.content, s.context
        FROM snippets s JOIN assets a ON a.id = s.asset_id
        {where}
        ORDER BY s.id LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    snippets = [
        {
            "asset_id": row["asset_id"],
            "title": row["title"],
            "kind": row["kind"],
            "lang": row["lang"],
            "tool": row["tool"],
            "content": row["content"],
            "context": row["context"],
        }
        for row in rows
    ]
    return {"snippets": snippets, "count": len(snippets)}
