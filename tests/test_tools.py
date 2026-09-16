from pathlib import Path

from seckb.pipeline.importer import import_file
from seckb.retrieval import HybridRetriever
from seckb.tools import kb_card, kb_get, kb_search, kb_snippets


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


def test_kb_get_returns_sections_and_truncates(kb, tmp_path: Path):
    body = "## 第一节\n\n" + "第一节内容。" * 40 + "\n\n## 第二节\n\n第二节内容。"
    asset_id = make_asset(kb, tmp_path, "a.md", "提权笔记", body)
    full = kb_get(kb.conn, asset_id, max_tokens=10000)
    assert full["truncated"] is False
    assert "第一节内容" in full["content"]
    assert any("第二节" in section for section in full["sections"])

    section = kb_get(kb.conn, asset_id, section="第一节", max_tokens=10000)
    assert "第一节内容" in section["content"]
    assert "第二节内容" not in section["content"]

    clipped = kb_get(kb.conn, asset_id, max_tokens=30)
    assert clipped["truncated"] is True
    assert clipped["token_estimate"] <= 60


def test_kb_get_missing_returns_none(kb):
    assert kb_get(kb.conn, 99999) is None


def test_kb_snippets_filters(kb, tmp_path: Path):
    asset_id = make_asset(
        kb,
        tmp_path,
        "a.md",
        "nmap 笔记",
        "扫描记录：\n\n```bash\nnmap -sV -p445 10.0.0.1\n```\n",
    )
    resp = kb_snippets(kb.conn, query="nmap -sV")
    assert resp["count"] >= 1
    assert resp["snippets"][0]["asset_id"] == asset_id
    assert resp["snippets"][0]["kind"] == "oneliner"
    assert resp["snippets"][0]["tool"] is None
    by_kind = kb_snippets(kb.conn, kind="oneliner")
    assert by_kind["count"] >= 1
    empty = kb_snippets(kb.conn, query="绝不存在的片段xyz")
    assert empty["count"] == 0


def test_kb_card_includes_cve_structured_fields(kb, tmp_path: Path):
    src = tmp_path / "cve.md"
    src.write_text("# CVE-2017-0144\n\nSMBv1 远程代码执行。", encoding="utf-8")
    asset_id = import_file(
        kb.conn,
        kb.settings,
        src,
        asset_type="cve",
        source="kev",
        source_id="CVE-2017-0144",
        extra={"cve_id": "CVE-2017-0144", "cvss": 9.8, "cwe": "CWE-311", "in_kev": True},
    ).asset_id
    card = kb_card(kb.conn, asset_id)
    assert card["cve"]["cvss"] == 9.8
    assert card["cve"]["cwe"] == "CWE-311"
    assert card["cve"]["in_kev"] is True


def test_kb_get_clips_oversized_first_block(kb, tmp_path: Path):
    body = "## 长章节\n\n" + "内容句子。" * 300
    asset_id = make_asset(kb, tmp_path, "long.md", "长文", body)
    result = kb_get(kb.conn, asset_id, section="长章节", max_tokens=50)
    assert result["content"]
    assert result["truncated"] is True
    assert result["token_estimate"] <= 90
