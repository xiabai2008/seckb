from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from seckb.config import Settings
from seckb.enrich.llm import LLMProvider
from seckb.enrich.parser import Enrichment, parse_enrichment
from seckb.enrich.prompts import build_prompt
from seckb.pipeline.entities import link_entity
from seckb.utils.tokens import estimate_tokens


@dataclass
class QueueReport:
    processed: int = 0
    succeeded: int = 0
    failed: int = 0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def enqueue(conn: sqlite3.Connection, asset_id: int, kind: str = "summary") -> int:
    cursor = conn.execute(
        "INSERT INTO jobs(asset_id, kind, status, created_at) VALUES(?,?, 'pending', ?)",
        (asset_id, kind, _now()),
    )
    conn.commit()
    return cursor.lastrowid


def pending_jobs(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM jobs WHERE status = 'pending' ORDER BY id LIMIT ?", (limit,)
    ).fetchall()


def _asset_text(conn: sqlite3.Connection, asset_id: int, max_input_tokens: int) -> str:
    chunks = conn.execute(
        "SELECT content_md FROM chunks WHERE asset_id = ? ORDER BY seq", (asset_id,)
    ).fetchall()
    parts: list[str] = []
    total = 0
    for chunk in chunks:
        tokens = estimate_tokens(chunk["content_md"])
        if parts and total + tokens > max_input_tokens:
            break
        parts.append(chunk["content_md"])
        total += tokens
    return "\n\n".join(parts)


def save_card(
    conn: sqlite3.Connection,
    asset_id: int,
    enrichment: Enrichment,
    *,
    model: str | None,
) -> None:
    card_json = json.dumps(
        {
            "summary": enrichment.summary,
            "key_takeaways": enrichment.key_takeaways,
            "tags": enrichment.tags,
            "entities": enrichment.entities,
        },
        ensure_ascii=False,
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO cards(asset_id, summary, key_takeaways, card_json, model, generated_at)
        VALUES(?,?,?,?,?,?)
        """,
        (
            asset_id,
            enrichment.summary,
            json.dumps(enrichment.key_takeaways, ensure_ascii=False),
            card_json,
            model,
            _now(),
        ),
    )


def _merge_tags(conn: sqlite3.Connection, asset_id: int, new_tags: list[str]) -> None:
    row = conn.execute("SELECT tags FROM assets WHERE id = ?", (asset_id,)).fetchone()
    existing = json.loads(row["tags"] or "[]") if row else []
    merged = list(dict.fromkeys([*existing, *new_tags]))
    conn.execute(
        "UPDATE assets SET tags = ? WHERE id = ?",
        (json.dumps(merged, ensure_ascii=False), asset_id),
    )


def _save_entities(conn: sqlite3.Connection, asset_id: int, enrichment: Enrichment) -> None:
    for kind, names in enrichment.entities.items():
        for name in names:
            link_entity(conn, asset_id, kind, name)


def _save_snippets(conn: sqlite3.Connection, asset_id: int, enrichment: Enrichment) -> None:
    for snippet in enrichment.snippets:
        exists = conn.execute(
            "SELECT id FROM snippets WHERE asset_id = ? AND content = ?",
            (asset_id, snippet["content"]),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO snippets(asset_id, kind, lang, tool, content, context) VALUES(?,?,?,?,?,?)",
            (
                asset_id,
                snippet["kind"],
                snippet["lang"],
                snippet["tool"],
                snippet["content"],
                snippet["context"],
            ),
        )


def _mark_job(
    conn: sqlite3.Connection, job_id: int, *, status: str, error: str | None = None
) -> None:
    conn.execute(
        """
        UPDATE jobs SET status = ?, attempts = attempts + 1, last_error = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, error, _now(), job_id),
    )
    conn.commit()


def process_jobs(
    conn: sqlite3.Connection,
    settings: Settings,
    provider: LLMProvider,
    *,
    limit: int = 10,
) -> QueueReport:
    queue_config = (settings.enrich or {}).get("queue") or {}
    max_input_tokens = int(queue_config.get("max_input_tokens", 6000))
    max_attempts = int(queue_config.get("max_attempts", 3))
    report = QueueReport()
    for job in pending_jobs(conn, limit):
        report.processed += 1
        asset = conn.execute(
            "SELECT * FROM assets WHERE id = ?", (job["asset_id"],)
        ).fetchone()
        if asset is None:
            _mark_job(conn, job["id"], status="failed", error="资产不存在")
            report.failed += 1
            continue
        text = _asset_text(conn, job["asset_id"], max_input_tokens)
        prompt = build_prompt(asset["title"], text)
        try:
            raw = provider.complete(prompt)
            enrichment = parse_enrichment(raw)
        except Exception as exc:  # noqa: BLE001 - LLM 调用/解析失败需标记任务并继续
            attempts = job["attempts"] + 1
            status = "failed" if attempts >= max_attempts else "pending"
            _mark_job(conn, job["id"], status=status, error=str(exc))
            report.failed += 1
            continue
        save_card(conn, job["asset_id"], enrichment, model=getattr(provider, "model", None))
        _merge_tags(conn, job["asset_id"], enrichment.tags)
        _save_entities(conn, job["asset_id"], enrichment)
        _save_snippets(conn, job["asset_id"], enrichment)
        _mark_job(conn, job["id"], status="done")
        report.succeeded += 1
    return report
