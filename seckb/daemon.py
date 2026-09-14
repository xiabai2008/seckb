from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler

from seckb.collect import collect_all
from seckb.config import Settings, load_settings
from seckb.db.connection import init_db
from seckb.enrich.llm import build_provider
from seckb.enrich.queue import process_jobs


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
    every_minutes = (settings.schedule.get("enrich") or {}).get("every_minutes")
    if every_minutes:
        scheduler.add_job(
            _enrich_job,
            "interval",
            id="enrich",
            minutes=int(every_minutes),
        )
    return scheduler
