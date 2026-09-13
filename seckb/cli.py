from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from seckb.config import Settings, load_settings
from seckb.db.connection import init_db
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


def main() -> None:
    app()
