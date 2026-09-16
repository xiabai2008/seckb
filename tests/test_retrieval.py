from pathlib import Path

from seckb.indexer.meili import MeiliError
from seckb.indexer.vectors import EmbeddingError, FakeEmbedder, index_assets
from seckb.pipeline.importer import import_file
from seckb.retrieval import Candidate, HybridRetriever, expand_query, rrf_fuse


def test_rrf_fuse_single_pool_keeps_order():
    pools = [("fts", [Candidate(1, 11, 1), Candidate(2, 12, 2)])]
    fused = rrf_fuse(pools, k=60)
    assert [item.asset_id for item in fused] == [1, 2]
    assert fused[0].matched_by == {"fts"}
    assert fused[0].chunk_id == 11


def test_rrf_fuse_multi_pool_boosts_overlap():
    pools = [
        ("fts", [Candidate(1, 11, 1), Candidate(2, 12, 2)]),
        ("vector", [Candidate(2, 22, 1), Candidate(3, 33, 2)]),
    ]
    fused = rrf_fuse(pools, k=60)
    assert fused[0].asset_id == 2
    assert fused[0].matched_by == {"fts", "vector"}
    assert fused[0].chunk_id == 12
    assert fused[1].score > fused[2].score


def test_rrf_fuse_meili_asset_level_candidate():
    pools = [
        ("fts", [Candidate(1, 11, 1)]),
        ("meili", [Candidate(1, None, 1)]),
    ]
    fused = rrf_fuse(pools, k=60)
    assert fused[0].asset_id == 1
    assert fused[0].chunk_id == 11
    assert fused[0].matched_by == {"fts", "meili"}


class StubMeili:
    def __init__(self, hits=None, error=None):
        self.hits = hits or []
        self.error = error

    def search(self, query, *, limit=10, filters=None, index="assets"):
        if self.error:
            raise MeiliError(self.error)
        return list(self.hits)


def make_kb_asset(kb, tmp_path: Path, name: str, title: str, body: str) -> int:
    src = tmp_path / name
    src.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    return import_file(kb.conn, kb.settings, src).asset_id


def test_hybrid_search_fuses_three_sources(kb, tmp_path: Path):
    a1 = make_kb_asset(kb, tmp_path, "a.md", "永恒之蓝复现", "MS17-010 永恒之蓝利用记录。")
    a2 = make_kb_asset(kb, tmp_path, "b.md", "提权笔记", "Linux 提权常见手法汇总。")
    embedder = FakeEmbedder()
    index_assets(kb.conn, kb.settings, embedder, [a1, a2], batch_size=10)
    meili = StubMeili(hits=[{"id": a1, "title": "永恒之蓝复现"}, {"id": a2, "title": "提权笔记"}])
    retriever = HybridRetriever(kb.conn, kb.settings, meili=meili, embedder=embedder)
    response = retriever.search("永恒之蓝")
    assert response.degraded == []
    assert response.results
    assert response.results[0].asset_id == a1
    assert response.results[0].matched_by == ["fts", "meili", "vector"]


def test_hybrid_search_degrades_when_backend_fails(kb, tmp_path: Path):
    a1 = make_kb_asset(kb, tmp_path, "a.md", "永恒之蓝复现", "MS17-010 永恒之蓝利用记录。")

    class BrokenEmbedder:
        def embed(self, texts):
            raise EmbeddingError("ollama down")

    retriever = HybridRetriever(
        kb.conn, kb.settings, meili=StubMeili(error="meili down"), embedder=BrokenEmbedder()
    )
    response = retriever.search("永恒之蓝")
    assert response.results
    assert response.results[0].asset_id == a1
    assert "meili" in response.degraded
    assert "vector" in response.degraded


def test_hybrid_search_type_and_tag_filters(kb, tmp_path: Path):
    make_kb_asset(kb, tmp_path, "a.md", "永恒之蓝复现", "MS17-010 永恒之蓝利用记录。")
    cve = make_kb_asset(kb, tmp_path, "b.md", "Log4Shell 记录", "CVE-2021-44228 漏洞利用记录。")
    retriever = HybridRetriever(kb.conn, kb.settings, meili=None, embedder=None)
    by_type = retriever.search("永恒之蓝", asset_type="post")
    assert by_type.results
    assert all(item.type == "post" for item in by_type.results)
    kb.conn.execute("UPDATE assets SET tags = '[\"log4j\"]' WHERE id = ?", (cve,))
    kb.conn.commit()
    by_tag = retriever.search("CVE-2021-44228", tag="log4j")
    assert [item.asset_id for item in by_tag.results] == [cve]


def test_expand_query_with_aliases():
    aliases = {"永恒之蓝": ["MS17-010", "CVE-2017-0144"], "脏牛": ["CVE-2016-5195"]}
    assert expand_query("永恒之蓝怎么利用", aliases) == ["MS17-010", "CVE-2017-0144"]
    assert expand_query("MS17-010 永恒之蓝", aliases) == ["CVE-2017-0144"]
    assert expand_query("普通查询", aliases) == []
    assert expand_query("LOG4SHELL 利用", {"log4shell": ["CVE-2021-44228"]}) == ["CVE-2021-44228"]


def test_hybrid_search_alias_expansion_finds_cve(kb, tmp_path: Path):
    cve = make_kb_asset(
        kb, tmp_path, "cve.md", "CVE-2017-0144 KEV", "Microsoft SMBv1 remote code execution."
    )
    kb.settings.taxonomy = {
        **kb.settings.taxonomy,
        "aliases": {"永恒之蓝": ["MS17-010", "CVE-2017-0144"]},
    }
    retriever = HybridRetriever(kb.conn, kb.settings, meili=None, embedder=None)
    response = retriever.search("永恒之蓝利用")
    assert [item.asset_id for item in response.results] == [cve]
    assert "fts_alias" in response.results[0].matched_by
