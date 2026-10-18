from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"


def load_dashboard_html() -> str:
    return (STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")


def _group(conn: sqlite3.Connection, sql: str) -> list[dict]:
    return [
        {"name": row[0] or "未知", "count": row[1]}
        for row in conn.execute(sql).fetchall()
    ]


def build_stats(conn: sqlite3.Connection) -> dict:
    totals = {
        "assets": conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0],
        "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        "cards": conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0],
        "snippets": conn.execute("SELECT COUNT(*) FROM snippets").fetchone()[0],
        "entities": conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
    }
    cves = {
        "total": conn.execute("SELECT COUNT(*) FROM cves").fetchone()[0],
        "with_cvss": conn.execute(
            "SELECT COUNT(*) FROM cves WHERE cvss IS NOT NULL"
        ).fetchone()[0],
        "in_kev": conn.execute("SELECT COUNT(*) FROM cves WHERE in_kev = 1").fetchone()[0],
    }
    cutoff = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")
    growth = [
        {"date": row[0], "count": row[1]}
        for row in conn.execute(
            """
            SELECT substr(imported_at, 1, 10) AS day, COUNT(*)
            FROM assets WHERE substr(imported_at, 1, 10) >= ?
            GROUP BY day ORDER BY day
            """,
            (cutoff,),
        ).fetchall()
    ]
    top_tools = [
        {"name": row[0], "count": row[1]}
        for row in conn.execute(
            """
            SELECT e.name, COUNT(*) AS n
            FROM asset_entities ae JOIN entities e ON e.id = ae.entity_id
            WHERE e.kind = 'tool'
            GROUP BY e.name ORDER BY n DESC LIMIT 12
            """
        ).fetchall()
    ]
    recent = [
        {
            "id": row["id"],
            "type": row["type"],
            "title": row["title"],
            "source": row["source"],
            "imported_at": row["imported_at"],
        }
        for row in conn.execute(
            "SELECT id, type, title, source, imported_at FROM assets ORDER BY id DESC LIMIT 12"
        ).fetchall()
    ]
    return {
        "totals": totals,
        "cves": cves,
        "by_type": _group(conn, "SELECT type, COUNT(*) FROM assets GROUP BY type ORDER BY 2 DESC"),
        "by_source": _group(
            conn, "SELECT source, COUNT(*) FROM assets GROUP BY source ORDER BY 2 DESC"
        ),
        "by_lang": _group(conn, "SELECT lang, COUNT(*) FROM assets GROUP BY lang ORDER BY 2 DESC"),
        "by_category": _group(
            conn,
            "SELECT category, COUNT(*) FROM assets GROUP BY category ORDER BY 2 DESC LIMIT 12",
        ),
        "growth": growth,
        "top_tools": top_tools,
        "recent": recent,
    }


def list_assets(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    asset_type: str | None = None,
    source: str | None = None,
    category: str | None = None,
    lang: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    conditions: list[str] = []
    params: list = []
    if q:
        conditions.append("a.title LIKE ?")
        params.append(f"%{q}%")
    for column, value in (
        ("type", asset_type),
        ("source", source),
        ("category", category),
        ("lang", lang),
    ):
        if value:
            conditions.append(f"a.{column} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    total = conn.execute(f"SELECT COUNT(*) FROM assets a {where}", params).fetchone()[0]
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"""
        SELECT a.id, a.type, a.title, a.source, a.category, a.lang, a.tags,
               a.published_at, a.imported_at, (c.asset_id IS NOT NULL) AS has_card
        FROM assets a LEFT JOIN cards c ON c.asset_id = a.id
        {where}
        ORDER BY a.id DESC LIMIT ? OFFSET ?
        """,
        (*params, page_size, offset),
    ).fetchall()
    items = [
        {
            "id": row["id"],
            "type": row["type"],
            "title": row["title"],
            "source": row["source"],
            "category": row["category"],
            "lang": row["lang"],
            "tags": json.loads(row["tags"] or "[]"),
            "published_at": row["published_at"],
            "imported_at": row["imported_at"],
            "has_card": bool(row["has_card"]),
        }
        for row in rows
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}
