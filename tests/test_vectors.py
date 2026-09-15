import json
from pathlib import Path

import httpx

from seckb.indexer.vectors import (
    FakeEmbedder,
    OllamaEmbedder,
    build_embedder,
    index_asset,
    search_vectors,
)
from seckb.net import build_client
from seckb.pipeline.importer import import_file


def make_asset(kb, tmp_path: Path, name: str, title: str, body: str) -> int:
    src = tmp_path / name
    src.write_text(f"# {title}\n\n{body}", encoding="utf-8")
    return import_file(kb.conn, kb.settings, src).asset_id


def test_ollama_embedder_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "bge-m3"
        assert payload["input"] == ["a", "b"]
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    client = build_client(transport=httpx.MockTransport(handler))
    embedder = OllamaEmbedder(client=client)
    assert embedder.embed(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]


def test_build_embedder_defaults_to_ollama():
    embedder = build_embedder({})
    assert isinstance(embedder, OllamaEmbedder)


def test_index_and_search_exact_match(kb, tmp_path: Path):
    asset_id = make_asset(kb, tmp_path, "a.md", "永恒之蓝", "MS17-010 永恒之蓝利用记录")
    embedder = FakeEmbedder()
    assert index_asset(kb.conn, kb.settings, embedder, asset_id) >= 1
    chunk_text = kb.conn.execute(
        "SELECT content_md FROM chunks WHERE asset_id = ? ORDER BY seq", (asset_id,)
    ).fetchone()["content_md"]
    hits = search_vectors(kb.settings, embedder, chunk_text, limit=3)
    assert hits and hits[0].asset_id == asset_id


def test_reindex_is_idempotent(kb, tmp_path: Path):
    import lancedb

    asset_id = make_asset(kb, tmp_path, "b.md", "提权笔记", "Linux 提权常见手法")
    embedder = FakeEmbedder()
    index_asset(kb.conn, kb.settings, embedder, asset_id)
    index_asset(kb.conn, kb.settings, embedder, asset_id)
    db = lancedb.connect(str(kb.root / "meta" / "lancedb"))
    table = db.open_table("chunks")
    assert table.count_rows() == 1


def test_search_without_index_returns_empty(kb):
    assert search_vectors(kb.settings, FakeEmbedder(), "任意查询") == []


def test_index_assets_batched_and_idempotent(kb, tmp_path: Path):
    from seckb.indexer.vectors import index_assets

    a1 = make_asset(kb, tmp_path, "a.md", "甲", "内容甲。")
    a2 = make_asset(kb, tmp_path, "b.md", "乙", "内容乙。")
    embedder = FakeEmbedder()
    assert index_assets(kb.conn, kb.settings, embedder, [a1, a2], batch_size=1) == 2
    assert index_assets(kb.conn, kb.settings, embedder, [a1, a2], batch_size=100) == 0
