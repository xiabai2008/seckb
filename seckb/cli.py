from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from seckb import tools as kb_tools
from seckb.collect import collect_all
from seckb.config import Settings, load_settings
from seckb.daemon import build_scheduler
from seckb.db.connection import init_db
from seckb.enrich.llm import build_provider
from seckb.enrich.queue import process_jobs
from seckb.indexer.meili import build_meili_client
from seckb.indexer.meili import rebuild as rebuild_meili
from seckb.indexer.vectors import build_embedder, index_assets
from seckb.pipeline.importer import import_file, scan_inbox
from seckb.retrieval import build_retriever

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
    type: str = typer.Option(None, "--type"),
    tag: str = typer.Option(None, "--tag"),
) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    retriever = build_retriever(conn, settings)
    response = kb_tools.kb_search(conn, retriever, query, type=type, tag=tag, limit=limit)
    results = response["results"]
    table = Table(title=f"搜索：{query}（{len(results)} 条）")
    table.add_column("id", width=6)
    table.add_column("类型", width=8)
    table.add_column("标题", max_width=36)
    table.add_column("命中", width=14)
    table.add_column("片段", max_width=46)
    for item in results:
        table.add_row(
            str(item["asset_id"]),
            item["type"],
            item["title"],
            ",".join(item["matched_by"]),
            item["snippet"],
        )
    console.print(table)
    if response["degraded"]:
        console.print(f"[yellow]降级检索（不可用：{', '.join(response['degraded'])}）[/yellow]")
    conn.close()


@app.command()
def card(ctx: typer.Context, asset_id: int = typer.Argument(...)) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    data = kb_tools.kb_card(conn, asset_id)
    if data is None:
        console.print("[red]资产不存在[/red]")
        raise typer.Exit(code=1)
    console.print(f"[bold]{data['title']}[/bold] ({data['type']}, id={asset_id})")
    console.print(f"标签: {', '.join(data['tags']) or '-'}")
    console.print(f"摘要: {data['summary'] or '（未富化）'}")
    for takeaway in data["key_takeaways"]:
        console.print(f"  - {takeaway}")
    for kind, names in (data["entities"] or {}).items():
        if names:
            console.print(f"实体[{kind}]: {', '.join(names)}")
    conn.close()


@app.command("get")
def get_cmd(
    ctx: typer.Context,
    asset_id: int = typer.Argument(...),
    max_tokens: int = typer.Option(2000, "--max-tokens"),
    section: str = typer.Option(None, "--section"),
) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    data = kb_tools.kb_get(conn, asset_id, section=section, max_tokens=max_tokens)
    if data is None:
        console.print("[red]资产不存在[/red]")
        raise typer.Exit(code=1)
    console.print(data["content"])
    if data["truncated"]:
        console.print(f"[yellow]（已截断，约 {data['token_estimate']} tokens）[/yellow]")
    conn.close()


@app.command()
def snippets(
    ctx: typer.Context,
    query: str = typer.Argument(None),
    tool: str = typer.Option(None, "--tool"),
    kind: str = typer.Option(None, "--kind"),
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    response = kb_tools.kb_snippets(conn, query=query, tool=tool, kind=kind, limit=limit)
    table = Table(title=f"片段（{response['count']} 条）")
    table.add_column("资产", width=6)
    table.add_column("类型", width=10)
    table.add_column("工具", width=12)
    table.add_column("内容", max_width=60)
    for item in response["snippets"]:
        table.add_row(
            str(item["asset_id"]), item["kind"] or "-", item["tool"] or "-", item["content"]
        )
    console.print(table)
    conn.close()


@app.command()
def mcp(ctx: typer.Context) -> None:
    from seckb.mcp_server import run_stdio

    Console(stderr=True).print("seckb MCP server started (stdio) - Ctrl+C to stop")
    run_stdio()


@app.command()
def serve(ctx: typer.Context, port: int = typer.Option(8011, "--port")) -> None:
    import uvicorn

    from seckb.api import create_app

    settings: Settings = ctx.obj
    conn = _open(settings)
    retriever = build_retriever(conn, settings)
    application = create_app(conn, settings, retriever)
    console.print(f"HTTP API 监听 http://127.0.0.1:{port}（Ctrl+C 停止）")
    uvicorn.run(application, host="127.0.0.1", port=port, log_level="warning")


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
def enrich(
    ctx: typer.Context,
    limit: int = typer.Option(10, "--limit", "-n"),
    drain: bool = typer.Option(False, "--drain", help="循环处理直到队列排空"),
) -> None:
    settings: Settings = ctx.obj
    provider = build_provider(settings.enrich)
    if provider is None:
        console.print("[red]未配置 LLM API Key（环境变量 DEEPSEEK_API_KEY），无法富化[/red]")
        raise typer.Exit(code=1)
    conn = _open(settings)
    total_processed = 0
    total_succeeded = 0
    total_failed = 0
    while True:
        report = process_jobs(conn, settings, provider, limit=limit)
        total_processed += report.processed
        total_succeeded += report.succeeded
        total_failed += report.failed
        console.print(
            f"批次：处理 {report.processed}，成功 {report.succeeded}，失败 {report.failed}；"
            f"累计成功 {total_succeeded}"
        )
        if not drain or report.processed == 0:
            break
    console.print(
        f"富化完成：处理 {total_processed}，成功 {total_succeeded}，失败 {total_failed}"
    )
    conn.close()


@app.command()
def embed(
    ctx: typer.Context,
    batch: int = typer.Option(500, "--batch", help="每批提交的切片数"),
) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    embedder = build_embedder(settings.enrich)
    asset_ids = [row["id"] for row in conn.execute("SELECT id FROM assets ORDER BY id")]
    console.print(f"向量化开始：{len(asset_ids)} 个资产，批大小 {batch}")
    total = index_assets(
        conn,
        settings,
        embedder,
        asset_ids,
        batch_size=batch,
        progress=lambda added: console.print(f"  已提交 {added} 个切片"),
    )
    console.print(f"向量化完成：新增 {total} 个切片")
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
def eval(
    ctx: typer.Context,
    top: int = typer.Option(5, "--top"),
    cases: Annotated[Path | None, typer.Option("--cases")] = None,
) -> None:
    from seckb.eval import DEFAULT_CASES_PATH, load_cases, run_eval

    settings: Settings = ctx.obj
    conn = _open(settings)
    retriever = build_retriever(conn, settings)
    path = Path(cases) if cases else DEFAULT_CASES_PATH
    report = run_eval(retriever, load_cases(path), top=top)
    table = Table(title=f"检索评测（命中 {report.passed}/{report.total}）")
    table.add_column("查询", max_width=30)
    table.add_column("结果", width=6)
    table.add_column("Top 命中", max_width=60)
    for detail in report.details:
        table.add_row(detail.query, "通过" if detail.passed else "未中", " | ".join(detail.top_titles[:3]))
    console.print(table)
    console.print(f"命中率：{report.hit_rate:.0%}")
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
