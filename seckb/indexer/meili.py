from __future__ import annotations

import json
import os
import sqlite3

import httpx

from seckb.net import build_client

INDEX = "assets"
CONTENT_CHAR_LIMIT = 4000


class MeiliError(Exception):
    pass


class MeiliClient:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:7700",
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or build_client()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def ensure_index(self, index: str = INDEX) -> None:
        response = self.client.post(
            f"{self.base_url}/indexes",
            json={"uid": index, "primaryKey": "id"},
            headers=self._headers(),
        )
        if response.status_code not in (200, 201, 409):
            raise MeiliError(f"创建索引失败: HTTP {response.status_code}")
        response = self.client.patch(
            f"{self.base_url}/indexes/{index}/settings",
            json={
                "searchableAttributes": ["title", "summary", "tags", "content"],
                "filterableAttributes": ["type", "tags", "source", "lang"],
            },
            headers=self._headers(),
        )
        if response.status_code >= 400:
            raise MeiliError(f"更新索引设置失败: HTTP {response.status_code}")

    def upsert(self, docs: list[dict], index: str = INDEX) -> None:
        response = self.client.post(
            f"{self.base_url}/indexes/{index}/documents",
            json=docs,
            headers=self._headers(),
        )
        if response.status_code not in (200, 202):
            raise MeiliError(f"写入文档失败: HTTP {response.status_code}")

    def search(
        self, query: str, *, limit: int = 10, filters: str | None = None, index: str = INDEX
    ) -> list[dict]:
        payload: dict = {"q": query, "limit": limit}
        if filters:
            payload["filter"] = filters
        response = self.client.post(
            f"{self.base_url}/indexes/{index}/search",
            json=payload,
            headers=self._headers(),
        )
        if response.status_code >= 400:
            raise MeiliError(f"检索失败: HTTP {response.status_code}")
        return response.json().get("hits", [])


def build_doc(conn: sqlite3.Connection, asset_id: int) -> dict:
    asset = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if asset is None:
        raise MeiliError(f"资产不存在: {asset_id}")
    card = conn.execute("SELECT summary FROM cards WHERE asset_id = ?", (asset_id,)).fetchone()
    chunks = conn.execute(
        "SELECT content_md FROM chunks WHERE asset_id = ? ORDER BY seq", (asset_id,)
    ).fetchall()
    content = "\n\n".join(chunk["content_md"] for chunk in chunks)[:CONTENT_CHAR_LIMIT]
    return {
        "id": asset_id,
        "type": asset["type"],
        "title": asset["title"],
        "lang": asset["lang"],
        "source": asset["source"],
        "source_url": asset["source_url"],
        "category": asset["category"],
        "published_at": asset["published_at"],
        "tags": json.loads(asset["tags"] or "[]"),
        "summary": card["summary"] if card else "",
        "content": content,
    }


def index_asset(conn: sqlite3.Connection, client, asset_id: int) -> None:
    client.upsert([build_doc(conn, asset_id)])


def rebuild(conn: sqlite3.Connection, client, *, batch_size: int = 100) -> int:
    ids = [row["id"] for row in conn.execute("SELECT id FROM assets ORDER BY id")]
    total = 0
    batch: list[dict] = []
    for asset_id in ids:
        batch.append(build_doc(conn, asset_id))
        if len(batch) >= batch_size:
            client.upsert(batch)
            total += len(batch)
            batch = []
    if batch:
        client.upsert(batch)
        total += len(batch)
    return total


def build_meili_client(config: dict, *, client: httpx.Client | None = None) -> MeiliClient:
    meili = (config or {}).get("meili") or {}
    api_key = os.environ.get(meili.get("api_key_env", "MEILI_MASTER_KEY"))
    return MeiliClient(
        base_url=meili.get("base_url", "http://127.0.0.1:7700"),
        api_key=api_key,
        client=client,
    )
