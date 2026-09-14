from __future__ import annotations

import hashlib
import sqlite3
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
