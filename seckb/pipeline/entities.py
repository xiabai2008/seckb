from __future__ import annotations

import sqlite3


def link_entity(conn: sqlite3.Connection, asset_id: int, kind: str, name: str) -> int:
    canonical = name.lower()
    row = conn.execute(
        "SELECT id FROM entities WHERE kind = ? AND canonical = ?", (kind, canonical)
    ).fetchone()
    if row:
        entity_id = row["id"]
    else:
        cursor = conn.execute(
            "INSERT INTO entities(kind, name, canonical) VALUES(?,?,?)", (kind, name, canonical)
        )
        entity_id = cursor.lastrowid
    conn.execute(
        "INSERT OR IGNORE INTO asset_entities(asset_id, entity_id) VALUES(?,?)",
        (asset_id, entity_id),
    )
    return entity_id
