from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from seckb.config import Settings
from seckb.connectors.base import RawItem
from seckb.pipeline.importer import import_file
from seckb.utils.hashing import slugify


@dataclass
class IngestStats:
    imported: int = 0
    duplicated: int = 0
    skipped: int = 0
    updated: int = 0


def _find_by_source_id(conn: sqlite3.Connection, source: str, source_id: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM assets WHERE source = ? AND source_id = ?", (source, source_id)
    ).fetchone()
    return row["id"] if row else None


def _find_cve_asset(conn: sqlite3.Connection, source_id: str) -> int | None:
    row = conn.execute(
        """SELECT a.id FROM assets a JOIN cves c ON c.asset_id = a.id
           WHERE a.source_id = ? ORDER BY a.id LIMIT 1""",
        (source_id,),
    ).fetchone()
    return row["id"] if row else None


def ingest_items(
    conn: sqlite3.Connection,
    settings: Settings,
    items: list[RawItem],
    *,
    source: str = "unknown",
) -> IngestStats:
    stats = IngestStats()
    tmp_dir = settings.kb_root / "meta" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for item in items:
        if item.source_id and _find_by_source_id(conn, source, item.source_id):
            stats.skipped += 1
            continue
        if item.extra.get("in_kev") and item.source_id:
            asset_id = _find_cve_asset(conn, item.source_id)
            if asset_id is not None:
                conn.execute("UPDATE cves SET in_kev = 1 WHERE asset_id = ?", (asset_id,))
                conn.commit()
                stats.updated += 1
                continue
        content = item.content
        if not content.lstrip().startswith("# "):
            content = f"# {item.title}\n\n{content}"
        tmp_path = tmp_dir / f"ingest-{slugify(item.source_id or item.title)}.md"
        tmp_path.write_text(content, encoding="utf-8")
        report = import_file(
            conn,
            settings,
            tmp_path,
            asset_type=item.asset_type,
            source=source,
            source_url=item.url,
            published_at=item.published_at,
            source_id=item.source_id,
            extra=item.extra,
        )
        if report.status == "imported" and report.asset_id is not None:
            conn.execute(
                "INSERT INTO jobs(asset_id, kind, status, created_at) VALUES(?, 'summary', 'pending', ?)",
                (report.asset_id, datetime.now(UTC).isoformat(timespec="seconds")),
            )
            conn.commit()
            stats.imported += 1
        else:
            stats.duplicated += 1
    return stats
