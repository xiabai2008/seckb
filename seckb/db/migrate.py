from __future__ import annotations

import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME_RE = re.compile(r"^(\d{4})_.*\.sql$")


def _migrations() -> list[tuple[int, Path]]:
    items: list[tuple[int, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = _NAME_RE.match(path.name)
        if match:
            items.append((int(match.group(1)), path))
    return items


def migrate(conn: sqlite3.Connection) -> int:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, path in _migrations():
        if version <= current:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {version}")
        current = version
    conn.commit()
    return current
