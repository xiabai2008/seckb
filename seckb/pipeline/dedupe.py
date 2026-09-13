from __future__ import annotations

import sqlite3

from seckb.utils.simhash import from_signed64, hamming, simhash64


def find_by_sha256(conn: sqlite3.Connection, sha256: str) -> int | None:
    row = conn.execute("SELECT id FROM assets WHERE sha256 = ?", (sha256,)).fetchone()
    return row["id"] if row else None


def find_near_duplicate(conn: sqlite3.Connection, text: str, *, threshold: int = 3) -> int | None:
    fingerprint = simhash64(text)
    rows = conn.execute("SELECT id, simhash FROM assets WHERE simhash IS NOT NULL")
    for row in rows:
        if hamming(from_signed64(row["simhash"]), fingerprint) <= threshold:
            return row["id"]
    return None
