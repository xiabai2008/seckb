from __future__ import annotations

import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from seckb import __version__
from seckb import tools as kb_tools
from seckb.config import Settings
from seckb.dashboard import build_stats, list_assets, load_dashboard_html
from seckb.retrieval import HybridRetriever
from seckb.services import ServiceManager


def create_app(
    conn: sqlite3.Connection,
    settings: Settings,
    retriever: HybridRetriever,
    services: ServiceManager | None = None,
) -> FastAPI:
    app = FastAPI(title="seckb", version=__version__)
    manager = services or ServiceManager(settings)

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return load_dashboard_html()

    @app.get("/stats")
    def stats() -> dict:
        return build_stats(conn)

    @app.get("/assets")
    def assets(
        q: str | None = None,
        type: str | None = None,
        source: str | None = None,
        category: str | None = None,
        lang: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        return list_assets(
            conn,
            q=q,
            asset_type=type,
            source=source,
            category=category,
            lang=lang,
            page=page,
            page_size=page_size,
        )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/services/status")
    def services_status() -> dict:
        return manager.status()

    @app.post("/services/start")
    def services_start(what: str = "all") -> dict:
        try:
            return manager.start(what)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/services/stop")
    def services_stop(what: str = "all") -> dict:
        try:
            return manager.stop(what)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/search")
    def search(
        q: str, type: str | None = None, tag: str | None = None, limit: int = 8
    ) -> dict:
        return kb_tools.kb_search(conn, retriever, q, type=type, tag=tag, limit=limit)

    @app.get("/card/{asset_id}")
    def card(asset_id: int) -> dict:
        data = kb_tools.kb_card(conn, asset_id)
        if data is None:
            raise HTTPException(status_code=404, detail="asset not found")
        return data

    @app.get("/get/{asset_id}")
    def get_content(asset_id: int, section: str | None = None, max_tokens: int = 2000) -> dict:
        data = kb_tools.kb_get(conn, asset_id, section=section, max_tokens=max_tokens)
        if data is None:
            raise HTTPException(status_code=404, detail="asset not found")
        return data

    @app.get("/snippets")
    def snippets(
        q: str | None = None,
        tool: str | None = None,
        kind: str | None = None,
        asset_id: int | None = None,
        limit: int = 10,
    ) -> dict:
        return kb_tools.kb_snippets(
            conn, query=q, tool=tool, kind=kind, asset_id=asset_id, limit=limit
        )

    return app
