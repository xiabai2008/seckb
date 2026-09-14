from pathlib import Path

from seckb.config import Settings
from seckb.daemon import build_scheduler, parse_cron


def test_parse_cron():
    assert parse_cron("0 */6 * * *") == {
        "minute": "0",
        "hour": "*/6",
        "day": "*",
        "month": "*",
        "day_of_week": "*",
    }


def test_build_scheduler_registers_jobs():
    settings = Settings(
        kb_root=Path("D:/KB"),
        schedule={
            "collect": {"rss": "0 */6 * * *", "nvd": "0 3 * * *"},
            "enrich": {"every_minutes": 10},
        },
    )
    scheduler = build_scheduler(settings)
    ids = sorted(job.id for job in scheduler.get_jobs())
    assert ids == ["collect:nvd", "collect:rss", "enrich"]
