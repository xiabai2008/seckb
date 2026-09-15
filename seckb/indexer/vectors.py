from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import httpx

from seckb.config import Settings
from seckb.net import build_client

TABLE = "chunks"


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "bge-m3",
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = client or build_client(timeout=60.0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self.client.post(
            f"{self.base_url}/api/embed",
            json={"model": self.model, "input": texts},
        )
        if response.status_code >= 400:
            raise EmbeddingError(f"Ollama HTTP {response.status_code}: {response.text[:200]}")
        embeddings = response.json().get("embeddings")
        if not embeddings or len(embeddings) != len(texts):
            raise EmbeddingError("Ollama 返回的向量数量不符")
        return embeddings


class FakeEmbedder:
    dim = 16

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            raw = [digest[i % len(digest)] / 255.0 - 0.5 for i in range(self.dim)]
            norm = sum(value * value for value in raw) ** 0.5 or 1.0
            vectors.append([value / norm for value in raw])
        return vectors


@dataclass
class VectorHit:
    chunk_id: int
    asset_id: int
    score: float


def _connect(settings: Settings):
    import lancedb

    return lancedb.connect(str(settings.kb_root / "meta" / "lancedb"))


def _table_exists(db) -> bool:
    try:
        db.open_table(TABLE)
        return True
    except Exception:  # noqa: BLE001 - LanceDB 未就绪时降级为空索引
        return False


def index_asset(
    conn: sqlite3.Connection, settings: Settings, embedder: Embedder, asset_id: int
) -> int:
    rows = conn.execute(
        "SELECT id, heading_path, content_md FROM chunks WHERE asset_id = ? ORDER BY seq",
        (asset_id,),
    ).fetchall()
    if not rows:
        return 0
    texts = [
        f"{row['heading_path']}\n{row['content_md']}" if row["heading_path"] else row["content_md"]
        for row in rows
    ]
    vectors = embedder.embed(texts)
    records = [
        {"chunk_id": row["id"], "asset_id": asset_id, "vector": vector}
        for row, vector in zip(rows, vectors)
    ]
    db = _connect(settings)
    if _table_exists(db):
        table = db.open_table(TABLE)
        table.delete(f"asset_id = {int(asset_id)}")
        table.add(records)
    else:
        db.create_table(TABLE, data=records)
    return len(records)


def index_assets(
    conn: sqlite3.Connection,
    settings: Settings,
    embedder: Embedder,
    asset_ids: list[int],
    *,
    batch_size: int = 200,
    progress: Callable[[int], None] | None = None,
) -> int:
    db = _connect(settings)
    table = db.open_table(TABLE) if _table_exists(db) else None
    existing: set[int] = set()
    if table is not None:
        existing = {int(value) for value in table.to_arrow()["chunk_id"].to_pylist()}
    pending: list[dict] = []
    added = 0

    def flush() -> None:
        nonlocal table, pending, added
        if not pending:
            return
        if table is None:
            table = db.create_table(TABLE, data=pending)
        else:
            table.add(pending)
        added += len(pending)
        pending = []
        if progress is not None:
            progress(added)

    for asset_id in asset_ids:
        rows = conn.execute(
            "SELECT id, heading_path, content_md FROM chunks WHERE asset_id = ? ORDER BY seq",
            (asset_id,),
        ).fetchall()
        rows = [
            row
            for row in rows
            if int(row["id"]) not in existing and str(row["content_md"]).strip()
        ]
        if not rows:
            continue
        texts = [
            (
                f"{row['heading_path']}\n{row['content_md']}"
                if row["heading_path"]
                else row["content_md"]
            )[:8000]
            for row in rows
        ]
        try:
            vectors = embedder.embed(texts)
        except EmbeddingError:
            vectors, rows = _embed_one_by_one(embedder, rows, texts)
            if not rows:
                continue
        pending.extend(
            {"chunk_id": row["id"], "asset_id": asset_id, "vector": vector}
            for row, vector in zip(rows, vectors)
        )
        if len(pending) >= batch_size:
            flush()
    flush()
    return added


def _embed_one_by_one(
    embedder: Embedder, rows: list, texts: list[str]
) -> tuple[list[list[float]], list]:
    vectors: list[list[float]] = []
    keep: list = []
    for row, text in zip(rows, texts):
        try:
            vectors.append(embedder.embed([text])[0])
            keep.append(row)
        except EmbeddingError:
            continue
    return vectors, keep


def search_vectors(
    settings: Settings, embedder: Embedder, query: str, *, limit: int = 10
) -> list[VectorHit]:
    db = _connect(settings)
    if not _table_exists(db):
        return []
    table = db.open_table(TABLE)
    if table.count_rows() == 0:
        return []
    vector = embedder.embed([query])[0]
    hits: list[VectorHit] = []
    for row in table.search(vector).limit(limit).to_list():
        distance = float(row.get("_distance", 0.0))
        hits.append(
            VectorHit(
                chunk_id=int(row["chunk_id"]),
                asset_id=int(row["asset_id"]),
                score=1.0 / (1.0 + distance),
            )
        )
    return hits


def build_embedder(config: dict, *, client: httpx.Client | None = None) -> Embedder:
    embedding = (config or {}).get("embedding") or {}
    provider = embedding.get("provider", "ollama")
    if provider == "ollama":
        return OllamaEmbedder(
            base_url=embedding.get("base_url", "http://127.0.0.1:11434"),
            model=embedding.get("model", "bge-m3"),
            client=client,
        )
    raise ValueError(f"未知 embedding provider: {provider}")
