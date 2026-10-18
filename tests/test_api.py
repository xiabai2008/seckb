from pathlib import Path

from fastapi.testclient import TestClient

from seckb.api import create_app
from seckb.pipeline.importer import import_file
from seckb.retrieval import HybridRetriever


def make_client(kb, tmp_path: Path) -> tuple[TestClient, int]:
    src = tmp_path / "post.md"
    src.write_text(
        "# 永恒之蓝复现\n\nMS17-010 利用记录。\n\n```bash\nnmap -sV -p445 10.0.0.1\n```\n",
        encoding="utf-8",
    )
    asset_id = import_file(kb.conn, kb.settings, src).asset_id
    kb.conn.execute(
        "INSERT INTO cards(asset_id, summary, key_takeaways, card_json, model, generated_at)"
        " VALUES(?, '永恒之蓝摘要', '[\"要点\"]', '{}', 'fake', 'now')",
        (asset_id,),
    )
    kb.conn.commit()
    retriever = HybridRetriever(kb.conn, kb.settings)
    return TestClient(create_app(kb.conn, kb.settings, retriever)), asset_id


def test_api_health(kb, tmp_path: Path):
    client, _ = make_client(kb, tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_search_and_card(kb, tmp_path: Path):
    client, asset_id = make_client(kb, tmp_path)
    response = client.get("/search", params={"q": "永恒之蓝"})
    assert response.status_code == 200
    body = response.json()
    assert body["results"][0]["asset_id"] == asset_id

    response = client.get(f"/card/{asset_id}")
    assert response.status_code == 200
    assert response.json()["summary"] == "永恒之蓝摘要"

    assert client.get("/card/99999").status_code == 404


def test_api_get_and_snippets(kb, tmp_path: Path):
    client, asset_id = make_client(kb, tmp_path)
    response = client.get(f"/get/{asset_id}", params={"max_tokens": 20})
    assert response.status_code == 200
    assert response.json()["truncated"] is True or response.json()["token_estimate"] <= 40

    response = client.get("/snippets", params={"kind": "oneliner"})
    assert response.status_code == 200
    assert response.json()["count"] >= 1


def test_api_dashboard_page(kb, tmp_path: Path):
    client, _ = make_client(kb, tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "seckb" in response.text
    assert "知识库" in response.text


def test_api_stats_and_assets(kb, tmp_path: Path):
    client, asset_id = make_client(kb, tmp_path)
    stats = client.get("/stats").json()
    assert stats["totals"]["assets"] == 1
    assert stats["totals"]["cards"] == 1
    assets = client.get("/assets", params={"type": "post"}).json()
    assert assets["total"] == 1
    assert assets["items"][0]["id"] == asset_id


def test_api_snippets_filter_by_asset(kb, tmp_path: Path):
    client, asset_id = make_client(kb, tmp_path)
    response = client.get("/snippets", params={"asset_id": asset_id})
    assert response.status_code == 200
    assert response.json()["count"] >= 1
    assert client.get("/snippets", params={"asset_id": 99999}).json()["count"] == 0


class FakeServiceManager:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"ollama": {"running": True}, "retrieval_ready": True}

    def start(self, what):
        self.calls.append(("start", what))
        if what not in ("search", "collect", "all"):
            raise ValueError("未知目标")
        return {"what": what, "actions": [], "status": self.status()}

    def stop(self, what):
        self.calls.append(("stop", what))
        if what not in ("search", "collect", "all"):
            raise ValueError("未知目标")
        return {"what": what, "actions": [], "status": self.status()}


def test_api_services_control(kb, tmp_path: Path):
    from seckb.api import create_app
    from seckb.retrieval import HybridRetriever

    fake = FakeServiceManager()
    retriever = HybridRetriever(kb.conn, kb.settings)
    client = TestClient(create_app(kb.conn, kb.settings, retriever, services=fake))

    assert client.get("/services/status").json()["retrieval_ready"] is True
    assert client.post("/services/start", params={"what": "search"}).status_code == 200
    assert client.post("/services/stop", params={"what": "all"}).status_code == 200
    assert client.post("/services/start", params={"what": "bogus"}).status_code == 400
    assert fake.calls == [("start", "search"), ("stop", "all"), ("start", "bogus")]
