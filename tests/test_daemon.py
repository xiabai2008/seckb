from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from seckb.config import Settings
from seckb.daemon import build_scheduler, is_offpeak, parse_cron

BJ = ZoneInfo("Asia/Shanghai")

OFFPEAK = {
    "enabled": True,
    "peak_windows": ["09:00-12:00", "14:00-18:00"],
    "holidays": ["2026-10-01"],
}


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


def test_build_scheduler_registers_embed_and_index():
    settings = Settings(
        kb_root=Path("D:/KB"),
        schedule={"embed": {"every_minutes": 30}, "index": {"every_minutes": 30}},
    )
    scheduler = build_scheduler(settings)
    ids = sorted(job.id for job in scheduler.get_jobs())
    assert ids == ["embed", "index"]


def test_offpeak_disabled_allows_any_time():
    assert is_offpeak({"enabled": False}, datetime(2026, 10, 19, 10, 0, tzinfo=BJ)) is True


def test_offpeak_weekday_peak_hours_blocked():
    # 2026-10-19 是周一，峰时 09:00-12:00 / 14:00-18:00
    for hour, minute in ((9, 0), (11, 59), (14, 0), (17, 59)):
        assert is_offpeak(OFFPEAK, datetime(2026, 10, 19, hour, minute, tzinfo=BJ)) is False


def test_offpeak_weekday_valley_hours_allowed():
    for hour, minute in ((0, 0), (8, 59), (12, 0), (13, 59), (18, 0), (23, 59)):
        assert is_offpeak(OFFPEAK, datetime(2026, 10, 19, hour, minute, tzinfo=BJ)) is True


def test_offpeak_weekend_all_day_allowed():
    # 2026-10-18 是周日
    for hour in (9, 15, 22):
        assert is_offpeak(OFFPEAK, datetime(2026, 10, 18, hour, 0, tzinfo=BJ)) is True


def test_offpeak_holiday_treated_as_valley():
    assert is_offpeak(OFFPEAK, datetime(2026, 10, 1, 10, 0, tzinfo=BJ)) is True
