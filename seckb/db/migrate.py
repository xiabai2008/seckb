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
    """按文件名顺序应用未执行的迁移；版本号由迁移脚本自己写入。

    迁移脚本末尾的 `PRAGMA user_version = N` 是版本推进的唯一来源，
    Python 侧不拼任何 SQL —— SQLite 的 PRAGMA 也不接受参数占位符。
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, path in _migrations():
        if version <= current:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        applied = conn.execute("PRAGMA user_version").fetchone()[0]
        if applied < version:
            raise RuntimeError(
                f"迁移 {path.name} 未把 user_version 推进到 {version}（当前 {applied}），"
                "请在脚本末尾补 `PRAGMA user_version = N;`"
            )
        current = applied
    conn.commit()
    return current
