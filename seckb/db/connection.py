from __future__ import annotations

import sqlite3
from pathlib import Path

from seckb.db.migrate import migrate

KB_DIRS = [
    "inbox",
    "books",
    "posts/zh",
    "posts/en",
    "repos",
    "vulndb",
    "ctf",
    "standards",
    "meta/logs",
    "meta/snapshots",
    "meta/tmp",
]


def open_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(kb_root: Path) -> sqlite3.Connection:
    for rel in KB_DIRS:
        (kb_root / rel).mkdir(parents=True, exist_ok=True)
    conn = open_db(kb_root / "meta" / "catalog.db")
    migrate(conn)
    return conn
