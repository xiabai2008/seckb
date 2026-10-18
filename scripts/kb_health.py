"""知识库体检：一次输出规模、采集健康度、富化积压与内容质量指标。

只读 catalog.db，不写任何数据，可随时运行。
人类可读摘要走 stdout，机器可读 JSON 用 --json 输出（供定时任务/看板消费）。

用法：
  .venv\\Scripts\\python.exe scripts\\kb_health.py
  .venv\\Scripts\\python.exe scripts\\kb_health.py --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seckb.config import load_settings

STALE_CRITICAL_DAYS = 2
STALE_WARN_DAYS = 1
MISC_RATIO_WARN = 0.60
ENRICH_PENDING_WARN = 500


def _connect(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def collect(conn: sqlite3.Connection) -> dict:
    now = datetime.now(timezone.utc)

    scale = {
        "assets": conn.execute("SELECT count(*) FROM assets").fetchone()[0],
        "chunks": conn.execute("SELECT count(*) FROM chunks").fetchone()[0],
        "cards": conn.execute("SELECT count(*) FROM cards").fetchone()[0],
        "snippets": conn.execute("SELECT count(*) FROM snippets").fetchone()[0],
        "entities": conn.execute("SELECT count(*) FROM entities").fetchone()[0],
        "cves": conn.execute("SELECT count(*) FROM cves").fetchone()[0],
    }

    sources = []
    for row in conn.execute("SELECT name, last_run_at, health FROM sources ORDER BY name"):
        last = _parse_ts(row["last_run_at"])
        stale_days = round((now - last).total_seconds() / 86400, 1) if last else None
        sources.append(
            {
                "name": row["name"],
                "last_run_at": row["last_run_at"],
                "stale_days": stale_days,
                # health 字段只在任务报错时才会变，不能代表真实状态
                "reported_health": row["health"],
                "status": "stale" if (stale_days or 0) > STALE_CRITICAL_DAYS else "ok" if stale_days is not None else "never",
            }
        )

    enrich = {"done": 0, "failed": 0, "pending": 0}
    for row in conn.execute("SELECT status, count(*) c FROM jobs GROUP BY status"):
        enrich[row["status"]] = row["c"]

    total_assets = scale["assets"] or 1
    quality = {
        "misc_ratio": round(
            conn.execute("SELECT count(*) FROM assets WHERE category='misc'").fetchone()[0] / total_assets, 4
        ),
        "no_tags": conn.execute(
            "SELECT count(*) FROM assets WHERE tags IS NULL OR tags IN ('', '[]')"
        ).fetchone()[0],
        "bad_published_at": conn.execute(
            "SELECT count(*) FROM assets WHERE published_at IS NOT NULL "
            "AND published_at NOT LIKE '____-__-__%'"
        ).fetchone()[0],
        "missing_cvss": conn.execute(
            "SELECT count(*) FROM cves WHERE cvss IS NULL OR cvss=''"
        ).fetchone()[0],
        "dup_titles": conn.execute(
            "SELECT count(*) FROM (SELECT title FROM assets GROUP BY title HAVING count(*) > 1)"
        ).fetchone()[0],
        "empty_summary": conn.execute(
            "SELECT count(*) FROM cards WHERE summary IS NULL OR summary=''"
        ).fetchone()[0],
        "hanging_runs": conn.execute(
            "SELECT count(*) FROM runs WHERE finished_at IS NULL"
        ).fetchone()[0],
    }
    quality["misc_assets"] = int(quality["misc_ratio"] * scale["assets"])

    alerts = []
    for s in sources:
        if s["status"] == "stale":
            alerts.append(
                {
                    "level": "critical" if (s["stale_days"] or 0) > STALE_CRITICAL_DAYS else "warning",
                    "metric": "collect_stale",
                    "message": f"采集源 {s['name']} 已停更 {s['stale_days']} 天（最后 {s['last_run_at'] or '从未'}）",
                }
            )
    if enrich["pending"] > ENRICH_PENDING_WARN:
        alerts.append(
            {
                "level": "warning",
                "metric": "enrich_backlog",
                "message": f"富化积压 {enrich['pending']} 条，超过阈值 {ENRICH_PENDING_WARN}",
            }
        )
    if quality["misc_ratio"] > MISC_RATIO_WARN:
        alerts.append(
            {
                "level": "warning",
                "metric": "category_misc",
                "message": f"{quality['misc_assets']} 条资产落在 misc（{quality['misc_ratio']:.0%}），分类失效",
            }
        )
    if quality["bad_published_at"] > 0:
        alerts.append(
            {
                "level": "warning",
                "metric": "published_at_format",
                "message": f"{quality['bad_published_at']} 条 published_at 非 ISO 格式，时间排序会失真",
            }
        )
    if quality["hanging_runs"] > 0:
        alerts.append(
            {
                "level": "warning",
                "metric": "hanging_runs",
                "message": f"{quality['hanging_runs']} 条采集运行无结束时间，疑似进程中途退出",
            }
        )

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "scale": scale,
        "sources": sources,
        "enrich": enrich,
        "quality": quality,
        "alerts": alerts,
        "verdict": "critical" if any(a["level"] == "critical" for a in alerts) else "warning" if alerts else "ok",
    }


def render(report: dict) -> str:
    s, q = report["scale"], report["quality"]
    lines = [
        f"知识库体检  {report['generated_at']}",
        f"结论: {report['verdict'].upper()}    告警: {len(report['alerts'])} 条",
        "",
        f"规模  资产 {s['assets']:,} · 切片 {s['chunks']:,} · 卡片 {s['cards']:,} · 片段 {s['snippets']:,} · 实体 {s['entities']:,} · CVE {s['cves']:,}",
        f"富化  完成 {report['enrich']['done']:,} · 失败 {report['enrich']['failed']} · 待处理 {report['enrich']['pending']}",
        f"质量  misc 占比 {q['misc_ratio']:.1%} · 无标签 {q['no_tags']} · 时间格式异常 {q['bad_published_at']} · "
        f"同标题重复 {q['dup_titles']} 组 · 缺 CVSS {q['missing_cvss']} · 空摘要 {q['empty_summary']}",
        "",
        "采集源（停更天数）",
    ]
    for src in report["sources"]:
        flag = "!!" if src["status"] == "stale" else "  "
        days = f"{src['stale_days']}d" if src["stale_days"] is not None else "never"
        lines.append(f"  {flag} {src['name']:<18} {days:>7}   {src['last_run_at'] or '-'}")
    if report["alerts"]:
        lines.append("")
        lines.append("告警")
        for a in report["alerts"]:
            lines.append(f"  [{a['level']}] {a['message']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args()

    settings = load_settings()
    conn = _connect(settings.db_path)
    try:
        report = collect(conn)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
