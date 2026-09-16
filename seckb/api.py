from __future__ import annotations

import sqlite3

from fastapi import FastAPI, HTTPException

from seckb import __version__
from seckb import tools as kb_tools
from seckb.config import Settings
from seckb.retrieval import HybridRetriever


def create_app(
    conn: sqlite3.Connection, settings: Settings, retriever: HybridRetriever
) -> FastAPI:
    app = FastAPI(title="seckb", version=__version__)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

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
        q: str | None = None, tool: str | None = None, kind: str | None = None, limit: int = 10
    ) -> dict:
        return kb_tools.kb_snippets(conn, query=q, tool=tool, kind=kind, limit=limit)

    return app
