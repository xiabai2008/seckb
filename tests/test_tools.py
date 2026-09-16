from pathlib import Path

from seckb.pipeline.importer import import_file
from seckb.retrieval import HybridRetriever
from seckb.tools import kb_card, kb_search


def make_asset(kb, tmp_path: Path, name: str, title: str, body: str) -> int:
    src = tmp_path / name
    src.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    return import_file(kb.conn, kb.settings, src).asset_id


def make_retriever(kb) -> HybridRetriever:
    return HybridRetriever(kb.conn, kb.settings, meili=None, embedder=None)


def test_kb_search_returns_results_with_citations(kb, tmp_path: Path):
    asset_id = make_asset(kb, tmp_path, "a.md", "永恒之蓝复现", "MS17-010 永恒之蓝利用记录。")
    response = kb_search(kb.conn, make_retriever(kb), "永恒之蓝")
    assert response["results"]
    first = response["results"][0]
    assert first["asset_id"] == asset_id
    assert first["title"] == "永恒之蓝复现"
    assert first["matched_by"] == ["fts"]
    assert response["token_estimate"] > 0
    assert response["degraded"] == []


def test_kb_search_empty_query_returns_empty(kb):
    response = kb_search(kb.conn, make_retriever(kb), "ab")
    assert response["results"] == []


def test_kb_card_returns_card_fields(kb, tmp_path: Path):
    asset_id = make_asset(kb, tmp_path, "a.md", "CVE-2021-44228", "Log4Shell 记录。")
    kb.conn.execute(
        """
        INSERT INTO cards(asset_id, summary, key_takeaways, card_json, model, generated_at)
        VALUES(?,?,?,?,?,?)
        """,
        (
            asset_id,
            "Log4Shell 摘要",
            '["要点一"]',
            '{"summary": "Log4Shell 摘要", "entities": {"cve": ["CVE-2021-44228"]}}',
            "fake",
            "now",
        ),
    )
    kb.conn.commit()
    card = kb_card(kb.conn, asset_id)
    assert card["summary"] == "Log4Shell 摘要"
    assert card["key_takeaways"] == ["要点一"]
    assert card["entities"]["cve"] == ["CVE-2021-44228"]
    assert card["title"] == "CVE-2021-44228"


def test_kb_card_missing_returns_none(kb):
    assert kb_card(kb.conn, 99999) is None
