import json

from seckb.collect import collect_all
from seckb.connectors.base import RawItem
from seckb.enrich.queue import process_jobs
from seckb.indexer.meili import build_doc
from seckb.indexer.vectors import FakeEmbedder, index_asset, search_vectors
from seckb.search import search

GOOD_JSON = json.dumps(
    {
        "summary": "永恒之蓝利用总结。",
        "key_takeaways": ["影响 SMBv1"],
        "tags": ["永恒之蓝"],
        "entities": {"cve": ["CVE-2017-0144"], "tool": ["nmap"]},
        "snippets": [
            {"kind": "command", "lang": "bash", "tool": "nmap", "content": "nmap -sV -p445 x", "context": ""}
        ],
    }
)


class FakeConnector:
    name = "fake"

    def fetch(self, cursor):
        return (
            [
                RawItem(
                    source_id="e2e-1",
                    title="永恒之蓝复现",
                    content="MS17-010 永恒之蓝利用记录。",
                    url="https://example.com/e2e",
                    published_at="2026-09-01T00:00:00",
                )
            ],
            cursor,
        )


class FakeLLM:
    model = "fake"

    def complete(self, prompt: str) -> str:
        return GOOD_JSON


def test_full_pipeline_v2(kb, monkeypatch):
    import seckb.collect as collect_mod

    monkeypatch.setattr(collect_mod, "build_connectors", lambda settings: {"fake": FakeConnector()})
    reports = collect_all(kb.conn, kb.settings)
    assert reports[0].imported == 1

    report = process_jobs(kb.conn, kb.settings, FakeLLM())
    assert report.succeeded == 1

    hits = search(kb.conn, "永恒之蓝")
    assert hits and hits[0].asset_id == 1

    asset_id = hits[0].asset_id
    embedder = FakeEmbedder()
    index_asset(kb.conn, kb.settings, embedder, asset_id)
    chunk_text = kb.conn.execute(
        "SELECT content_md FROM chunks WHERE asset_id = ? ORDER BY seq", (asset_id,)
    ).fetchone()["content_md"]
    vector_hits = search_vectors(kb.settings, embedder, chunk_text, limit=3)
    assert vector_hits and vector_hits[0].asset_id == asset_id

    doc = build_doc(kb.conn, asset_id)
    assert doc["summary"] == "永恒之蓝利用总结。"
    assert "永恒之蓝" in doc["tags"]
