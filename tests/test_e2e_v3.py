from pathlib import Path

from fastapi.testclient import TestClient

from seckb.api import create_app
from seckb.indexer.vectors import FakeEmbedder, index_assets
from seckb.pipeline.importer import import_file
from seckb.retrieval import HybridRetriever


class StubMeili:
    def __init__(self, hits):
        self.hits = hits

    def search(self, query, *, limit=10, filters=None, index="assets"):
        return list(self.hits)


def test_three_way_search_end_to_end(kb, tmp_path: Path):
    a1 = import_file(
        kb.conn,
        kb.settings,
        _write(tmp_path, "a.md", "# 永恒之蓝复现\n\nMS17-010 利用记录。"),
    ).asset_id
    a2 = import_file(
        kb.conn,
        kb.settings,
        _write(tmp_path, "b.md", "# 提权笔记\n\nLinux 提权手法。"),
    ).asset_id
    embedder = FakeEmbedder()
    index_assets(kb.conn, kb.settings, embedder, [a1, a2], batch_size=10)
    retriever = HybridRetriever(
        kb.conn, kb.settings, meili=StubMeili([{"id": a1}, {"id": a2}]), embedder=embedder
    )
    client = TestClient(create_app(kb.conn, kb.settings, retriever))
    body = client.get("/search", params={"q": "永恒之蓝"}).json()
    assert body["results"]
    assert body["degraded"] == []
    assert body["results"][0]["asset_id"] == a1
    assert "fts" in body["results"][0]["matched_by"]


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path
