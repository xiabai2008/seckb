from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from seckb.config import Settings
from seckb.connectors import build_connector
from seckb.connectors.base import Connector
from seckb.net import build_client
from seckb.pipeline.ingest import ingest_items


@dataclass
class RunReport:
    source: str
    fetched: int = 0
    imported: int = 0
    skipped: int = 0
    updated: int = 0
    error: str | None = None
    run_id: int = 0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def get_cursor(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute("SELECT last_cursor FROM sources WHERE name = ?", (name,)).fetchone()
    return row["last_cursor"] if row else None


def set_cursor(
    conn: sqlite3.Connection, name: str, cursor: str | None, *, health: str = "ok"
) -> None:
    conn.execute(
        """
        INSERT INTO sources(name, last_cursor, last_run_at, health) VALUES(?,?,?,?)
        ON CONFLICT(name) DO UPDATE SET
          last_cursor = excluded.last_cursor,
          last_run_at = excluded.last_run_at,
          health = excluded.health
        """,
        (name, cursor, _now(), health),
    )
    conn.commit()


def _record_run_start(conn: sqlite3.Connection, source: str) -> int:
    cursor = conn.execute(
        "INSERT INTO runs(source, started_at) VALUES(?,?)", (source, _now())
    )
    conn.commit()
    return cursor.lastrowid


def _record_run_finish(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    fetched: int = 0,
    imported: int = 0,
    skipped: int = 0,
    failed: int = 0,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE runs SET finished_at = ?, fetched = ?, imported = ?, skipped = ?,
                        failed = ?, error = ?
        WHERE id = ?
        """,
        (_now(), fetched, imported, skipped, failed, error, run_id),
    )
    conn.commit()


def run_source(
    conn: sqlite3.Connection, settings: Settings, connector: Connector
) -> RunReport:
    run_id = _record_run_start(conn, connector.name)
    cursor = get_cursor(conn, connector.name)
    try:
        items, new_cursor = connector.fetch(cursor)
    except Exception as exc:  # noqa: BLE001 - 采集失败需记录健康状态并降级
        set_cursor(conn, connector.name, cursor, health="error")
        _record_run_finish(conn, run_id, failed=1, error=str(exc))
        return RunReport(source=connector.name, error=str(exc), run_id=run_id)
    stats = ingest_items(conn, settings, items, source=connector.name)
    set_cursor(conn, connector.name, new_cursor or cursor, health="ok")
    _record_run_finish(
        conn,
        run_id,
        fetched=len(items),
        imported=stats.imported,
        skipped=stats.duplicated + stats.skipped,
    )
    return RunReport(
        source=connector.name,
        fetched=len(items),
        imported=stats.imported,
        skipped=stats.duplicated + stats.skipped,
        updated=stats.updated,
        run_id=run_id,
    )


def build_connectors(settings: Settings) -> dict[str, Connector]:
    client = build_client()
    connectors: dict[str, Connector] = {}
    for name, config in settings.sources.items():
        if not config.get("enabled", True):
            continue
        connectors[name] = build_connector(name, config, client)
    return connectors


def collect_all(
    conn: sqlite3.Connection, settings: Settings, *, only: str | None = None
) -> list[RunReport]:
    connectors = build_connectors(settings)
    reports: list[RunReport] = []
    for name, connector in connectors.items():
        if only and name != only:
            continue
        reports.append(run_source(conn, settings, connector))
    return reports
