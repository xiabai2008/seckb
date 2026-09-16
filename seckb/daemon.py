from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from seckb.collect import collect_all
from seckb.config import Settings, load_settings
from seckb.db.connection import init_db
from seckb.enrich.llm import build_provider
from seckb.enrich.queue import process_jobs
from seckb.indexer.meili import build_meili_client
from seckb.indexer.meili import rebuild as rebuild_meili
from seckb.indexer.vectors import build_embedder, index_assets

logger = logging.getLogger("seckb.daemon")


def parse_cron(expr: str) -> dict:
    minute, hour, day, month, day_of_week = expr.split()
    return {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": day_of_week,
    }


def _collect_job(source: str) -> None:
    settings = load_settings()
    conn = init_db(settings.kb_root)
    try:
        collect_all(conn, settings, only=source)
    finally:
        conn.close()


def _enrich_job() -> None:
    settings = load_settings()
    provider = build_provider(settings.enrich)
    if provider is None:
        return
    conn = init_db(settings.kb_root)
    try:
        limit = int((settings.enrich.get("queue") or {}).get("max_assets_per_run", 10))
        process_jobs(conn, settings, provider, limit=limit)
    finally:
        conn.close()


def _embed_job() -> None:
    settings = load_settings()
    try:
        embedder = build_embedder(settings.enrich)
    except Exception:  # noqa: BLE001 - 配置异常时跳过本轮
        return
    conn = init_db(settings.kb_root)
    try:
        asset_ids = [row["id"] for row in conn.execute("SELECT id FROM assets ORDER BY id")]
        index_assets(conn, settings, embedder, asset_ids, batch_size=500)
    except Exception:
        logger.exception("embed 任务失败，本轮跳过")
    finally:
        conn.close()


def _index_job() -> None:
    settings = load_settings()
    conn = init_db(settings.kb_root)
    try:
        client = build_meili_client(settings.enrich)
        client.ensure_index()
        rebuild_meili(conn, client)
    except Exception:
        logger.exception("index 任务失败，本轮跳过")
    finally:
        conn.close()


def build_scheduler(settings: Settings) -> BlockingScheduler:
    scheduler = BlockingScheduler()
    for name, expr in (settings.schedule.get("collect") or {}).items():
        scheduler.add_job(
            _collect_job,
            "cron",
            id=f"collect:{name}",
            kwargs={"source": name},
            **parse_cron(expr),
        )
    for key, job_func in (("enrich", _enrich_job), ("embed", _embed_job), ("index", _index_job)):
        every_minutes = (settings.schedule.get(key) or {}).get("every_minutes")
        if every_minutes:
            scheduler.add_job(
                job_func,
                "interval",
                id=key,
                minutes=int(every_minutes),
            )
    return scheduler
