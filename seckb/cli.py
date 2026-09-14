from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from seckb.collect import collect_all
from seckb.config import Settings, load_settings
from seckb.daemon import build_scheduler
from seckb.db.connection import init_db
from seckb.enrich.llm import build_provider
from seckb.enrich.queue import process_jobs
from seckb.indexer.meili import build_meili_client
from seckb.indexer.meili import rebuild as rebuild_meili
from seckb.indexer.vectors import build_embedder
from seckb.indexer.vectors import index_asset as index_vectors
from seckb.pipeline.importer import import_file, scan_inbox
from seckb.search import search as search_kb

app = typer.Typer(help="seckb - 面向 AI agent 的本地网络安全知识库", no_args_is_help=True)
console = Console()


def _open(settings: Settings) -> sqlite3.Connection:
    return init_db(settings.kb_root)


@app.callback()
def app_callback(
    ctx: typer.Context,
    config: Annotated[
        Path | None, typer.Option("--config", help="配置目录（含 settings.yaml / taxonomy.yaml）")
    ] = None,
) -> None:
    ctx.obj = load_settings(config)


@app.command()
def init(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    console.print(f"[green]知识库已初始化[/green] {settings.kb_root} (db: {settings.db_path})")
    conn.close()


@app.command("import")
def import_cmd(ctx: typer.Context, path: Annotated[Path, typer.Argument(exists=True)]) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    report = import_file(conn, settings, path)
    console.print(f"{report.status} asset_id={report.asset_id} path={report.path}")
    conn.close()


@app.command()
def scan(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    reports = scan_inbox(conn, settings)
    imported = sum(1 for r in reports if r.status == "imported")
    console.print(f"扫描完成：{len(reports)} 个文件，导入 {imported} 个")
    for report in reports:
        console.print(f"  {report.status} {report.path or ''}")
    conn.close()


@app.command()
def search(
    ctx: typer.Context,
    query: str = typer.Argument(...),
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    hits = search_kb(conn, query, limit=limit)
    table = Table(title=f"搜索：{query}（{len(hits)} 条）")
    table.add_column("id", width=6)
    table.add_column("标题", max_width=40)
    table.add_column("片段", max_width=60)
    for hit in hits:
        table.add_row(str(hit.asset_id), hit.title, hit.snippet)
    console.print(table)
    conn.close()


@app.command()
def stats(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    table = Table(title="知识库统计")
    table.add_column("指标")
    table.add_column("数量", justify="right")
    for asset_type, count in conn.execute(
        "SELECT type, COUNT(*) AS c FROM assets GROUP BY type ORDER BY c DESC"
    ):
        table.add_row(f"assets.{asset_type}", str(count))
    for metric, sql in (
        ("chunks", "SELECT COUNT(*) FROM chunks"),
        ("snippets", "SELECT COUNT(*) FROM snippets"),
        ("entities", "SELECT COUNT(*) FROM entities"),
    ):
        table.add_row(metric, str(conn.execute(sql).fetchone()[0]))
    console.print(table)
    console.print(f"知识库位置：{settings.kb_root}")
    conn.close()


@app.command()
def collect(ctx: typer.Context, source: str = typer.Option(None, "--source")) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    reports = collect_all(conn, settings, only=source)
    for report in reports:
        console.print(
            f"{report.source}: fetched={report.fetched} imported={report.imported} "
            f"skipped={report.skipped} updated={report.updated} error={report.error or '-'}"
        )
    conn.close()


@app.command()
def enrich(ctx: typer.Context, limit: int = typer.Option(10, "--limit", "-n")) -> None:
    settings: Settings = ctx.obj
    provider = build_provider(settings.enrich)
    if provider is None:
        console.print("[red]未配置 LLM API Key（环境变量 DEEPSEEK_API_KEY），无法富化[/red]")
        raise typer.Exit(code=1)
    conn = _open(settings)
    report = process_jobs(conn, settings, provider, limit=limit)
    console.print(
        f"富化完成：处理 {report.processed}，成功 {report.succeeded}，失败 {report.failed}"
    )
    conn.close()


@app.command()
def embed(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    embedder = build_embedder(settings.enrich)
    total = 0
    for row in conn.execute("SELECT id FROM assets ORDER BY id"):
        total += index_vectors(conn, settings, embedder, row["id"])
    console.print(f"向量化完成：{total} 个切片")
    conn.close()


@app.command()
def index(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    client = build_meili_client(settings.enrich)
    client.ensure_index()
    count = rebuild_meili(conn, client)
    console.print(f"Meilisearch 重建完成：{count} 个文档")
    conn.close()


@app.command()
def sources(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    table = Table(title="采集源")
    table.add_column("名称")
    table.add_column("类型")
    table.add_column("健康")
    table.add_column("上次运行")
    table.add_column("游标", max_width=40)
    health = {
        row["name"]: row
        for row in conn.execute("SELECT * FROM sources")
    }
    for name, config in settings.sources.items():
        row = health.get(name)
        table.add_row(
            name,
            str(config.get("type")),
            row["health"] if row else "-",
            row["last_run_at"] if row else "-",
            (row["last_cursor"] or "-") if row else "-",
        )
    console.print(table)
    conn.close()


@app.command()
def daemon(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj
    scheduler = build_scheduler(settings)
    console.print("守护进程启动，任务：" + ", ".join(job.id for job in scheduler.get_jobs()))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        console.print("守护进程已停止")


def main() -> None:
    app()
