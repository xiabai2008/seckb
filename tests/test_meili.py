import json
import os
from pathlib import Path

import httpx

from seckb.indexer.meili import MeiliClient, build_doc, build_meili_client, rebuild
from seckb.net import build_client
from seckb.pipeline.importer import import_file


class RecordingClient:
    def __init__(self):
        self.upserts: list[list[dict]] = []

    def upsert(self, docs, index="assets"):
        self.upserts.append(list(docs))


def make_asset(kb, tmp_path: Path, name: str, title: str, body: str) -> int:
    src = tmp_path / name
    src.write_text(f"# {title}\n\n{body}", encoding="utf-8")
    return import_file(kb.conn, kb.settings, src).asset_id


def test_build_doc_fields_and_card_summary(kb, tmp_path: Path):
    asset_id = make_asset(kb, tmp_path, "a.md", "永恒之蓝", "MS17-010 利用记录")
    kb.conn.execute(
        "INSERT INTO cards(asset_id, summary, key_takeaways, card_json, model, generated_at)"
        " VALUES(?,?,?,?,?,?)",
        (asset_id, "永恒之蓝摘要", "[]", "{}", "fake", "now"),
    )
    doc = build_doc(kb.conn, asset_id)
    assert doc["id"] == asset_id
    assert doc["title"] == "永恒之蓝"
    assert doc["type"] == "post"
    assert doc["summary"] == "永恒之蓝摘要"
    assert "MS17-010" in doc["content"]


def test_ensure_index_accepts_409_and_upsert_search():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/indexes" and request.method == "POST":
            return httpx.Response(409, json={"message": "index already exists"})
        if request.url.path.endswith("/settings"):
            return httpx.Response(200, json={})
        if request.url.path.endswith("/documents"):
            return httpx.Response(202, json={"taskUid": 1})
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"hits": [{"id": 1, "title": "命中"}]})
        return httpx.Response(404, text="nope")

    client = build_client(transport=httpx.MockTransport(handler))
    meili = MeiliClient(client=client)
    meili.ensure_index()
    meili.upsert([{"id": 1, "title": "x"}])
    hits = meili.search("x", limit=5)
    assert hits == [{"id": 1, "title": "命中"}]
    assert ("POST", "/indexes") in calls
    assert any(path.endswith("/search") for _, path in calls)


def test_rebuild_batches_all_assets(kb, tmp_path: Path):
    make_asset(kb, tmp_path, "a.md", "A", "内容 A")
    make_asset(kb, tmp_path, "b.md", "B", "内容 B")
    recorder = RecordingClient()
    assert rebuild(kb.conn, recorder) == 2
    assert len(recorder.upserts) == 1
    assert len(recorder.upserts[0]) == 2


def test_build_meili_client_reads_env(monkeypatch):
    monkeypatch.setenv("MEILI_MASTER_KEY", "master")
    client = build_meili_client({"meili": {"base_url": "http://127.0.0.1:7700"}})
    assert client.api_key == "master"
    monkeypatch.delenv("MEILI_MASTER_KEY", raising=False)
    assert build_meili_client({}).api_key is None
