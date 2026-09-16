# seckb P1c：融合检索与 Agent 接口 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把已入库的 7491 资产（FTS5 + Meilisearch + LanceDB 三路索引）融合成一个检索内核，并以 MCP Server + HTTP API 双接口暴露给渗透 agent，配一套真实场景评测集。

**Architecture:** `HybridRetriever` 统一调用三路检索（FTS5 关键词 / Meilisearch 关键词 / bge-m3 向量），用 RRF（Reciprocal Rank Fusion）融合排序，单路失败自动降级；`tools.py` 提供 4 个 agent 级函数（kb_search / kb_card / kb_get / kb_snippets）；MCP 与 FastAPI 都是这层的薄封装，共用同一内核。

**Tech Stack:** Python 3.12、mcp（官方 Python SDK）、FastAPI + uvicorn、PyYAML、pytest、ruff

**环境约定：** 所有命令在 `D:\HZR_PROJECTS\seckb` 执行，使用 `.venv\Scripts\python.exe`。所有单元测试不依赖外部服务（Meili/Ollama 用桩或降级路径）。

---

## 文件结构（本计划结束时）

```
seckb/
├── retrieval.py      # Candidate/SearchResult/SearchResponse + rrf_fuse + HybridRetriever + build_retriever
├── tools.py          # kb_search / kb_card / kb_get / kb_snippets（agent 级函数）
├── mcp_server.py     # build_server（FastMCP 注册）+ run_stdio
├── api.py            # create_app（FastAPI）
├── eval.py           # EvalCase / run_eval / load_cases
├── cli.py            # + card / get / snippets / mcp / serve / eval；search 升级为混合检索
tests/
├── test_retrieval.py test_tools.py test_mcp_server.py test_api.py test_eval.py test_cli_v3.py test_e2e_v3.py
└── eval/golden_queries.yaml
```

核心接口约定：

- `build_retriever(conn, settings) -> HybridRetriever`
- `retriever.search(query, asset_type=None, tag=None, limit=10) -> SearchResponse(results, degraded)`
- 工具函数签名：`kb_search(conn, retriever, query, type=None, tag=None, limit=8) -> dict` 等（全部纯函数，便于测试与复用）
- MCP 工具名：`kb_search` / `kb_card` / `kb_get` / `kb_snippets`；HTTP 路径：`/search` `/card/{id}` `/get/{id}` `/snippets` `/health`

---

### Task 1: 依赖与 RRF 融合

**Files:**
- Modify: `pyproject.toml`（追加 3 个依赖）
- Create: `seckb/retrieval.py`（本任务先实现数据模型与 rrf_fuse）
- Create: `tests/test_retrieval.py`

- [ ] **Step 1: 写失败测试**

`tests/test_retrieval.py`：

```python
from seckb.retrieval import Candidate, FusedCandidate, rrf_fuse


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_retrieval.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.retrieval'`

- [ ] **Step 3: 写最小实现**

`pyproject.toml` 的 `dependencies` 追加三行（放在 `"lancedb>=0.15",` 之后）：

```toml
    "mcp>=1.2",
    "fastapi>=0.115",
    "uvicorn>=0.30",
```

`seckb/retrieval.py`：

```python
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

from seckb.config import Settings
from seckb.indexer import fts
from seckb.indexer.vectors import search_vectors
from seckb.utils.tokens import estimate_tokens

RRF_K = 60
SNIPPET_LIMIT = 200


@dataclass
class Candidate:
    asset_id: int
    chunk_id: int | None
    rank: int


@dataclass
class FusedCandidate:
    asset_id: int
    score: float
    chunk_id: int | None
    matched_by: set[str] = field(default_factory=set)


@dataclass
class SearchResult:
    asset_id: int
    title: str
    type: str
    lang: str
    tags: list[str]
    category: str | None
    source: str
    source_url: str | None
    published_at: str | None
    summary: str
    snippet: str
    matched_by: list[str]
    score: float
    token_estimate: int


@dataclass
class SearchResponse:
    results: list[SearchResult]
    degraded: list[str] = field(default_factory=list)


def rrf_fuse(pools: list[tuple[str, list[Candidate]]], *, k: int = RRF_K) -> list[FusedCandidate]:
    scores: dict[int, float] = {}
    matched: dict[int, set[str]] = {}
    chunks: dict[int, int | None] = {}
    for name, candidates in pools:
        for candidate in candidates:
            scores[candidate.asset_id] = scores.get(candidate.asset_id, 0.0) + 1.0 / (
                k + candidate.rank
            )
            matched.setdefault(candidate.asset_id, set()).add(name)
            if candidate.asset_id not in chunks:
                chunks[candidate.asset_id] = candidate.chunk_id
    fused = [
        FusedCandidate(
            asset_id=asset_id,
            score=score,
            chunk_id=chunks[asset_id],
            matched_by=matched[asset_id],
        )
        for asset_id, score in scores.items()
    ]
    fused.sort(key=lambda item: (-item.score, item.asset_id))
    return fused


def _snippet(conn: sqlite3.Connection, chunk_id: int | None) -> str:
    if chunk_id is None:
        return ""
    row = conn.execute(
        "SELECT heading_path, content_md FROM chunks WHERE id = ?", (chunk_id,)
    ).fetchone()
    if row is None:
        return ""
    body = re.sub(r"\s+", " ", row["content_md"]).strip()
    heading = (row["heading_path"] or "").strip()
    text = f"{heading}: {body}" if heading else body
    return text[:SNIPPET_LIMIT]
```

- [ ] **Step 4: 安装依赖并运行测试**

Run:
```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest tests/test_retrieval.py -v
```
（pip 用 bash timeout 600000；若 mcp 安装失败，停止并报告）
Expected: `3 passed`

- [ ] **Step 5: 提交**

```powershell
git add pyproject.toml seckb/retrieval.py tests/test_retrieval.py
git commit -m "feat: RRF 融合与检索结果模型"
```

---

### Task 2: HybridRetriever（三路融合与降级）

**Files:**
- Modify: `seckb/retrieval.py`（追加 HybridRetriever）
- Modify: `tests/test_retrieval.py`（追加用例）

- [ ] **Step 1: 写失败测试（追加到 `tests/test_retrieval.py`）**

在文件顶部 import 区补充：

```python
from pathlib import Path

from seckb.indexer.meili import MeiliError
from seckb.indexer.vectors import EmbeddingError, FakeEmbedder, index_assets
from seckb.pipeline.importer import import_file
from seckb.retrieval import HybridRetriever
```

追加用例：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_retrieval.py -v`
Expected: FAIL（`ImportError: cannot import name 'HybridRetriever'`），且 `index_assets` 可导入

- [ ] **Step 3: 写最小实现（追加到 `seckb/retrieval.py` 末尾）**

```python
def build_retriever(conn: sqlite3.Connection, settings: Settings) -> "HybridRetriever":
    from seckb.indexer.meili import build_meili_client
    from seckb.indexer.vectors import build_embedder

    try:
        meili = build_meili_client(settings.enrich)
    except Exception:  # noqa: BLE001 - 索引客户端不可用时降级为关键词检索
        meili = None
    try:
        embedder = build_embedder(settings.enrich)
    except Exception:  # noqa: BLE001 - 嵌入不可用时降级为关键词检索
        embedder = None
    return HybridRetriever(conn, settings, meili=meili, embedder=embedder)


class HybridRetriever:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        *,
        meili=None,
        embedder=None,
    ) -> None:
        self.conn = conn
        self.settings = settings
        self.meili = meili
        self.embedder = embedder

    def _pools(
        self, query: str, candidate_limit: int, asset_type: str | None
    ) -> tuple[list[tuple[str, list[Candidate]]], list[str]]:
        pools: list[tuple[str, list[Candidate]]] = []
        degraded: list[str] = []
        fts_hits = fts.search(self.conn, query, limit=candidate_limit, asset_type=asset_type)
        pools.append(
            ("fts", [Candidate(hit.asset_id, hit.chunk_id, rank) for rank, hit in enumerate(fts_hits, 1)])
        )
        if self.meili is not None:
            try:
                filters = f'type = "{asset_type}"' if asset_type else None
                meili_hits = self.meili.search(query, limit=candidate_limit, filters=filters)
                pools.append(
                    (
                        "meili",
                        [
                            Candidate(int(hit["id"]), None, rank)
                            for rank, hit in enumerate(meili_hits, 1)
                        ],
                    )
                )
            except Exception:  # noqa: BLE001 - 单路失败降级并记录
                degraded.append("meili")
        if self.embedder is not None:
            try:
                vector_hits = search_vectors(
                    self.settings, self.embedder, query, limit=candidate_limit
                )
                pools.append(
                    (
                        "vector",
                        [
                            Candidate(hit.asset_id, hit.chunk_id, rank)
                            for rank, hit in enumerate(vector_hits, 1)
                        ],
                    )
                )
            except Exception:  # noqa: BLE001 - 单路失败降级并记录
                degraded.append("vector")
        return pools, degraded

    def _build_result(self, fused: FusedCandidate) -> SearchResult | None:
        row = self.conn.execute(
            """
            SELECT a.*, c.summary AS card_summary
            FROM assets a LEFT JOIN cards c ON c.asset_id = a.id
            WHERE a.id = ?
            """,
            (fused.asset_id,),
        ).fetchone()
        if row is None:
            return None
        snippet = _snippet(self.conn, fused.chunk_id)
        summary = row["card_summary"] or ""
        return SearchResult(
            asset_id=fused.asset_id,
            title=row["title"],
            type=row["type"],
            lang=row["lang"],
            tags=json.loads(row["tags"] or "[]"),
            category=row["category"],
            source=row["source"],
            source_url=row["source_url"],
            published_at=row["published_at"],
            summary=summary,
            snippet=snippet,
            matched_by=sorted(fused.matched_by),
            score=round(fused.score, 6),
            token_estimate=estimate_tokens(snippet) + estimate_tokens(summary) + 20,
        )

    def search(
        self,
        query: str,
        *,
        asset_type: str | None = None,
        tag: str | None = None,
        limit: int = 10,
    ) -> SearchResponse:
        candidate_limit = max(limit * 3, 20)
        pools, degraded = self._pools(query, candidate_limit, asset_type)
        fused_list = rrf_fuse(pools)
        results: list[SearchResult] = []
        for fused in fused_list:
            result = self._build_result(fused)
            if result is None:
                continue
            if asset_type and result.type != asset_type:
                continue
            if tag and tag not in result.tags:
                continue
            results.append(result)
            if len(results) >= limit:
                break
        return SearchResponse(results=results, degraded=degraded)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_retrieval.py -v`
Expected: `6 passed`

> 执行记录（2026-09-13）：发现 `search_vectors` 在无索引表时提前返回，嵌入后端故障无法被检测；已将 `embedder.embed` 调用移到早退判断之前（`seckb/indexer/vectors.py`），使 vector 降级可被感知，既有测试语义不变。

- [ ] **Step 5: 提交**

```powershell
git add seckb/retrieval.py tests/test_retrieval.py
git commit -m "feat: HybridRetriever 三路融合与降级"
```

---

### Task 3: Agent 工具层（kb_search / kb_card）

**Files:**
- Create: `seckb/tools.py`
- Create: `tests/test_tools.py`

- [ ] **Step 1: 写失败测试**

`tests/test_tools.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tools.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.tools'`

- [ ] **Step 3: 写最小实现**

`seckb/tools.py`：

```python
from __future__ import annotations

import json
import sqlite3

from seckb.retrieval import HybridRetriever, SearchResult


def _result_to_dict(result: SearchResult) -> dict:
    return {
        "asset_id": result.asset_id,
        "title": result.title,
        "type": result.type,
        "lang": result.lang,
        "tags": result.tags,
        "category": result.category,
        "source": result.source,
        "source_url": result.source_url,
        "published_at": result.published_at,
        "summary": result.summary,
        "snippet": result.snippet,
        "matched_by": result.matched_by,
        "score": result.score,
        "token_estimate": result.token_estimate,
    }


def kb_search(
    conn: sqlite3.Connection,
    retriever: HybridRetriever,
    query: str,
    *,
    type: str | None = None,
    tag: str | None = None,
    limit: int = 8,
) -> dict:
    response = retriever.search(query, asset_type=type, tag=tag, limit=limit)
    results = [_result_to_dict(item) for item in response.results]
    return {
        "query": query,
        "results": results,
        "degraded": response.degraded,
        "token_estimate": sum(item["token_estimate"] for item in results) + 50,
    }


def kb_card(conn: sqlite3.Connection, asset_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT a.title, a.type, a.lang, a.tags, a.category, a.source, a.source_url,
               a.published_at, c.summary, c.key_takeaways, c.card_json, c.model, c.generated_at
        FROM assets a LEFT JOIN cards c ON c.asset_id = a.id
        WHERE a.id = ?
        """,
        (asset_id,),
    ).fetchone()
    if row is None:
        return None
    card_json = {}
    if row["card_json"]:
        try:
            card_json = json.loads(row["card_json"])
        except json.JSONDecodeError:
            card_json = {}
    return {
        "asset_id": asset_id,
        "title": row["title"],
        "type": row["type"],
        "lang": row["lang"],
        "tags": json.loads(row["tags"] or "[]"),
        "category": row["category"],
        "source": row["source"],
        "source_url": row["source_url"],
        "published_at": row["published_at"],
        "has_card": row["summary"] is not None,
        "summary": row["summary"] or "",
        "key_takeaways": json.loads(row["key_takeaways"] or "[]"),
        "entities": card_json.get("entities", {}),
        "model": row["model"],
        "generated_at": row["generated_at"],
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tools.py -v`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/tools.py tests/test_tools.py
git commit -m "feat: Agent 工具层 kb_search/kb_card"
```

---

### Task 4: Agent 工具层（kb_get / kb_snippets）

**Files:**
- Modify: `seckb/tools.py`（追加两个函数）
- Modify: `tests/test_tools.py`（追加用例）

- [ ] **Step 1: 写失败测试（追加到 `tests/test_tools.py`）**

在文件顶部 import 区把 `from seckb.tools import kb_card, kb_search` 改为：

```python
from seckb.tools import kb_card, kb_get, kb_search, kb_snippets
```

追加用例：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tools.py -v`
Expected: FAIL，`ImportError: cannot import name 'kb_get'`

- [ ] **Step 3: 写最小实现（追加到 `seckb/tools.py` 末尾）**

```python
def kb_get(
    conn: sqlite3.Connection,
    asset_id: int,
    *,
    section: str | None = None,
    max_tokens: int = 2000,
) -> dict | None:
    asset = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if asset is None:
        return None
    rows = conn.execute(
        "SELECT heading_path, content_md FROM chunks WHERE asset_id = ? ORDER BY seq",
        (asset_id,),
    ).fetchall()
    sections: list[str] = []
    for row in rows:
        heading = (row["heading_path"] or "").strip()
        if heading and heading not in sections:
            sections.append(heading)
    if section:
        needle = section.lower()
        rows = [row for row in rows if needle in (row["heading_path"] or "").lower()]
    parts: list[str] = []
    total = 0
    truncated = False
    for row in rows:
        heading = (row["heading_path"] or "").strip()
        block = f"[{heading}]\n{row['content_md']}" if heading else row["content_md"]
        block_tokens = estimate_tokens(block)
        if parts and total + block_tokens > max_tokens:
            truncated = True
            break
        parts.append(block)
        total += block_tokens
    if len(parts) < len(rows):
        truncated = True
    content = "\n\n".join(parts)
    return {
        "asset_id": asset_id,
        "title": asset["title"],
        "type": asset["type"],
        "source": asset["source"],
        "source_url": asset["source_url"],
        "path": asset["path"],
        "content": content,
        "sections": sections,
        "truncated": truncated,
        "token_estimate": estimate_tokens(content) + 20,
    }


def kb_snippets(
    conn: sqlite3.Connection,
    *,
    query: str | None = None,
    tool: str | None = None,
    kind: str | None = None,
    limit: int = 10,
) -> dict:
    conditions: list[str] = []
    params: list = []
    if tool:
        conditions.append("s.tool = ?")
        params.append(tool)
    if kind:
        conditions.append("s.kind = ?")
        params.append(kind)
    if query:
        conditions.append("s.content LIKE ?")
        params.append(f"%{query}%")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"""
        SELECT s.asset_id, a.title, s.kind, s.lang, s.tool, s.content, s.context
        FROM snippets s JOIN assets a ON a.id = s.asset_id
        {where}
        ORDER BY s.id LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    snippets = [
        {
            "asset_id": row["asset_id"],
            "title": row["title"],
            "kind": row["kind"],
            "lang": row["lang"],
            "tool": row["tool"],
            "content": row["content"],
            "context": row["context"],
        }
        for row in rows
    ]
    return {"snippets": snippets, "count": len(snippets)}
```

把 `seckb/tools.py` 顶部的 import 改为：

```python
from seckb.retrieval import HybridRetriever, SearchResult
from seckb.utils.tokens import estimate_tokens
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tools.py -v`
Expected: `7 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/tools.py tests/test_tools.py
git commit -m "feat: Agent 工具层 kb_get/kb_snippets"
```

---

### Task 5: CLI 检索命令升级（search / card / get / snippets）

**Files:**
- Modify: `seckb/cli.py`
- Create: `tests/test_cli_v3.py`

- [ ] **Step 1: 写失败测试**

`tests/test_cli_v3.py`：

```python
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from seckb.cli import app

runner = CliRunner()


def write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "settings.yaml").write_text(
        f"kb_root: {(tmp_path / 'KB').as_posix()}\n", encoding="utf-8"
    )
    return cfg


def import_post(tmp_path: Path, cfg: Path, body: str) -> None:
    src = tmp_path / "post.md"
    src.write_text(body, encoding="utf-8")
    result = runner.invoke(app, ["--config", str(cfg), "import", str(src)])
    assert result.exit_code == 0


def test_cli_search_hybrid_output(tmp_path: Path):
    cfg = write_config(tmp_path)
    runner.invoke(app, ["--config", str(cfg), "init"])
    import_post(tmp_path, cfg, "# 永恒之蓝复现\n\nMS17-010 利用记录。")
    result = runner.invoke(app, ["--config", str(cfg), "search", "永恒之蓝"])
    assert result.exit_code == 0
    assert "永恒之蓝" in result.output
    assert "fts" in result.output


def test_cli_card_and_get(tmp_path: Path):
    cfg = write_config(tmp_path)
    runner.invoke(app, ["--config", str(cfg), "init"])
    import_post(tmp_path, cfg, "# 提权笔记\n\nLinux 提权常见手法。")
    db = sqlite3.connect(str(tmp_path / "KB" / "meta" / "catalog.db"))
    db.execute(
        "INSERT INTO cards(asset_id, summary, key_takeaways, card_json, model, generated_at)"
        " VALUES(1, '提权摘要', '[\"要点\"]', '{}', 'fake', 'now')"
    )
    db.commit()
    db.close()
    result = runner.invoke(app, ["--config", str(cfg), "card", "1"])
    assert result.exit_code == 0
    assert "提权摘要" in result.output
    result = runner.invoke(app, ["--config", str(cfg), "get", "1", "--max-tokens", "10000"])
    assert result.exit_code == 0
    assert "提权" in result.output


def test_cli_get_missing_exits_1(tmp_path: Path):
    cfg = write_config(tmp_path)
    runner.invoke(app, ["--config", str(cfg), "init"])
    result = runner.invoke(app, ["--config", str(cfg), "get", "999"])
    assert result.exit_code == 1


def test_cli_snippets(tmp_path: Path):
    cfg = write_config(tmp_path)
    runner.invoke(app, ["--config", str(cfg), "init"])
    import_post(
        tmp_path,
        cfg,
        "# 扫描笔记\n\n```bash\nnmap -sV -p445 10.0.0.1\n```\n",
    )
    result = runner.invoke(app, ["--config", str(cfg), "snippets", "--kind", "oneliner"])
    assert result.exit_code == 0
    assert "nmap" in result.output
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cli_v3.py -v`
Expected: FAIL（`card` / `get` / `snippets` 命令不存在）

- [ ] **Step 3: 写最小实现**

`seckb/cli.py` 修改：

1）import 区：删除 `from seckb.search import search as search_kb`，追加：

```python
from seckb.retrieval import build_retriever
from seckb import tools as kb_tools
```

2）`search` 命令完整替换为：

```python
@app.command()
def search(
    ctx: typer.Context,
    query: str = typer.Argument(...),
    limit: int = typer.Option(10, "--limit", "-n"),
    type: str = typer.Option(None, "--type"),
    tag: str = typer.Option(None, "--tag"),
) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    retriever = build_retriever(conn, settings)
    response = kb_tools.kb_search(conn, retriever, query, type=type, tag=tag, limit=limit)
    results = response["results"]
    table = Table(title=f"搜索：{query}（{len(results)} 条）")
    table.add_column("id", width=6)
    table.add_column("类型", width=8)
    table.add_column("标题", max_width=36)
    table.add_column("命中", width=14)
    table.add_column("片段", max_width=46)
    for item in results:
        table.add_row(
            str(item["asset_id"]),
            item["type"],
            item["title"],
            ",".join(item["matched_by"]),
            item["snippet"],
        )
    console.print(table)
    if response["degraded"]:
        console.print(f"[yellow]降级检索（不可用：{', '.join(response['degraded'])}）[/yellow]")
    conn.close()
```

3）在 `search` 之后追加三个命令：

```python
@app.command()
def card(ctx: typer.Context, asset_id: int = typer.Argument(...)) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    data = kb_tools.kb_card(conn, asset_id)
    if data is None:
        console.print("[red]资产不存在[/red]")
        raise typer.Exit(code=1)
    console.print(f"[bold]{data['title']}[/bold] ({data['type']}, id={asset_id})")
    console.print(f"标签: {', '.join(data['tags']) or '-'}")
    console.print(f"摘要: {data['summary'] or '（未富化）'}")
    for takeaway in data["key_takeaways"]:
        console.print(f"  - {takeaway}")
    for kind, names in (data["entities"] or {}).items():
        if names:
            console.print(f"实体[{kind}]: {', '.join(names)}")
    conn.close()


@app.command("get")
def get_cmd(
    ctx: typer.Context,
    asset_id: int = typer.Argument(...),
    max_tokens: int = typer.Option(2000, "--max-tokens"),
    section: str = typer.Option(None, "--section"),
) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    data = kb_tools.kb_get(conn, asset_id, section=section, max_tokens=max_tokens)
    if data is None:
        console.print("[red]资产不存在[/red]")
        raise typer.Exit(code=1)
    console.print(data["content"])
    if data["truncated"]:
        console.print(f"[yellow]（已截断，约 {data['token_estimate']} tokens）[/yellow]")
    conn.close()


@app.command()
def snippets(
    ctx: typer.Context,
    query: str = typer.Argument(None),
    tool: str = typer.Option(None, "--tool"),
    kind: str = typer.Option(None, "--kind"),
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    response = kb_tools.kb_snippets(conn, query=query, tool=tool, kind=kind, limit=limit)
    table = Table(title=f"片段（{response['count']} 条）")
    table.add_column("资产", width=6)
    table.add_column("类型", width=10)
    table.add_column("工具", width=12)
    table.add_column("内容", max_width=60)
    for item in response["snippets"]:
        table.add_row(
            str(item["asset_id"]), item["kind"] or "-", item["tool"] or "-", item["content"]
        )
    console.print(table)
    conn.close()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cli_v3.py tests/test_cli.py tests/test_cli_v2.py -v`
Expected: 全部通过（含既有 CLI 测试）

- [ ] **Step 5: 提交**

```powershell
git add seckb/cli.py tests/test_cli_v3.py
git commit -m "feat: CLI 混合检索与 card/get/snippets 命令"
```

---

### Task 6: MCP Server

**Files:**
- Create: `seckb/mcp_server.py`
- Modify: `seckb/cli.py`（追加 `mcp` 命令）
- Create: `tests/test_mcp_server.py`

- [ ] **Step 1: 写失败测试**

`tests/test_mcp_server.py`：

```python
import anyio

from seckb.mcp_server import build_server
from seckb.retrieval import HybridRetriever


def test_mcp_server_registers_expected_tools(kb):
    retriever = HybridRetriever(kb.conn, kb.settings)
    server = build_server(kb.conn, kb.settings, retriever)
    tools = anyio.run(server.list_tools)
    names = {tool.name for tool in tools}
    assert names == {"kb_search", "kb_card", "kb_get", "kb_snippets"}
    for tool in tools:
        assert tool.description
```

（若 `server.list_tools` 的 SDK 签名不同导致无法直接 `anyio.run`，改用 `anyio.run(lambda: server.list_tools())` 并保留名称断言。）

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_mcp_server.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.mcp_server'`

- [ ] **Step 3: 写最小实现**

`seckb/mcp_server.py`：

```python
from __future__ import annotations

import sqlite3

from mcp.server.fastmcp import FastMCP

from seckb.config import Settings, load_settings
from seckb.db.connection import init_db
from seckb import tools as kb_tools
from seckb.retrieval import HybridRetriever, build_retriever


def build_server(
    conn: sqlite3.Connection, settings: Settings, retriever: HybridRetriever
) -> FastMCP:
    server = FastMCP("seckb")

    @server.tool()
    def kb_search(
        query: str, type: str | None = None, tag: str | None = None, limit: int = 8
    ) -> dict:
        """混合检索本地网络安全知识库（漏洞库/帖子/仓库/靶场/书籍），返回带摘要、标签与出处的候选列表。query 支持中文或英文关键词、CVE 编号或自然语言问题。"""
        return kb_tools.kb_search(conn, retriever, query, type=type, tag=tag, limit=limit)

    @server.tool()
    def kb_card(asset_id: int) -> dict:
        """获取指定资产的完整知识卡片：摘要、要点、标签、CVE/工具/ATT&CK 实体。比搜索结果更详细，适合在 kb_search 命中后深入了解。"""
        data = kb_tools.kb_card(conn, asset_id)
        return data or {"error": "asset not found", "asset_id": asset_id}

    @server.tool()
    def kb_get(asset_id: int, section: str | None = None, max_tokens: int = 2000) -> dict:
        """按 token 预算取回资产正文切片（Markdown）。可选 section 按标题路径过滤。返回带 token_estimate 与截断标记，便于控制上下文开销。"""
        data = kb_tools.kb_get(conn, asset_id, section=section, max_tokens=max_tokens)
        return data or {"error": "asset not found", "asset_id": asset_id}

    @server.tool()
    def kb_snippets(
        query: str | None = None,
        tool: str | None = None,
        kind: str | None = None,
        limit: int = 10,
    ) -> dict:
        """检索可直接执行的命令/载荷/代码片段（含工具名与上下文），适合信息收集、漏洞利用与绕过场景取用。"""
        return kb_tools.kb_snippets(conn, query=query, tool=tool, kind=kind, limit=limit)

    return server


def run_stdio() -> None:
    settings = load_settings()
    conn = init_db(settings.kb_root)
    retriever = build_retriever(conn, settings)
    server = build_server(conn, settings, retriever)
    server.run()
```

`seckb/cli.py` 追加命令（注意：stdio 模式下 stdout 属于协议通道，所以提示信息只写 stderr）：

```python
@app.command()
def mcp(ctx: typer.Context) -> None:
    from seckb.mcp_server import run_stdio

    Console(stderr=True).print("seckb MCP server 启动（stdio），Ctrl+C 停止")
    run_stdio()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_mcp_server.py tests/test_cli_v3.py -v`
Expected: 全过；再跑 `.venv\Scripts\python.exe -m pytest -q` 确认无回归

> 执行记录（2026-09-13）：本机 mcp 2.2.0 已将 `FastMCP` 更名为 `MCPServer`（`mcp.server.fastmcp` 导入即报 ModuleNotFoundError）。实现改为 `from mcp.server.mcpserver import MCPServer`，`MCPServer("seckb")` 与返回注解同步替换，其余逻辑与计划一致。

- [ ] **Step 5: 提交**

```powershell
git add seckb/mcp_server.py seckb/cli.py tests/test_mcp_server.py
git commit -m "feat: MCP Server（kb_search/kb_card/kb_get/kb_snippets）"
```

---

### Task 7: HTTP API

**Files:**
- Create: `seckb/api.py`
- Modify: `seckb/cli.py`（追加 `serve` 命令）
- Create: `tests/test_api.py`

- [ ] **Step 1: 写失败测试**

`tests/test_api.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_api.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.api'`

- [ ] **Step 3: 写最小实现**

`seckb/api.py`：

```python
from __future__ import annotations

import sqlite3

from fastapi import FastAPI, HTTPException

from seckb import __version__
from seckb import tools as kb_tools
from seckb.config import Settings
from seckb.retrieval import HybridRetriever


def create_app(
    conn: sqlite3.Connection, settings: Settings, retriever: HybridRetriever
) -> FastAPI:
    app = FastAPI(title="seckb", version=__version__)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/search")
    def search(
        q: str, type: str | None = None, tag: str | None = None, limit: int = 8
    ) -> dict:
        return kb_tools.kb_search(conn, retriever, q, type=type, tag=tag, limit=limit)

    @app.get("/card/{asset_id}")
    def card(asset_id: int) -> dict:
        data = kb_tools.kb_card(conn, asset_id)
        if data is None:
            raise HTTPException(status_code=404, detail="asset not found")
        return data

    @app.get("/get/{asset_id}")
    def get_content(asset_id: int, section: str | None = None, max_tokens: int = 2000) -> dict:
        data = kb_tools.kb_get(conn, asset_id, section=section, max_tokens=max_tokens)
        if data is None:
            raise HTTPException(status_code=404, detail="asset not found")
        return data

    @app.get("/snippets")
    def snippets(
        q: str | None = None, tool: str | None = None, kind: str | None = None, limit: int = 10
    ) -> dict:
        return kb_tools.kb_snippets(conn, query=q, tool=tool, kind=kind, limit=limit)

    return app
```

`seckb/cli.py` 追加命令：

```python
@app.command()
def serve(ctx: typer.Context, port: int = typer.Option(8011, "--port")) -> None:
    import uvicorn

    from seckb.api import create_app

    settings: Settings = ctx.obj
    conn = _open(settings)
    retriever = build_retriever(conn, settings)
    application = create_app(conn, settings, retriever)
    console.print(f"HTTP API 监听 http://127.0.0.1:{port}（Ctrl+C 停止）")
    uvicorn.run(application, host="127.0.0.1", port=port, log_level="warning")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_api.py -v`
Expected: `3 passed`

> 执行记录（2026-09-16）：两处最小实现偏差，测试未改、断言未放宽。
> 1) FastAPI 把同步端点调度到线程池执行，而连接在测试主线程创建，`sqlite3` 线程亲和报 `ProgrammingError`；`seckb/db/connection.py` 的 `open_db` 改为 `sqlite3.connect(..., check_same_thread=False)`（Python 3.12 sqlite3 为 serialized 模式，跨线程共享安全）。
> 2) 计划内部矛盾：本任务测试要求单切片文档在 `max_tokens=20` 时 `truncated is True or token_estimate <= 40`，但 Task 4 的 `kb_get` 中 `if parts and ...` 守卫使首块永远豁免预算（实测响应 `{"truncated": false, "token_estimate": 50}`）。移除守卫使预算对首块同样生效，Task 4/5/6 既有测试语义不变（`tests/test_tools.py`、`tests/test_cli_v3.py` 全绿）。

- [ ] **Step 5: 提交**

```powershell
git add seckb/api.py seckb/cli.py tests/test_api.py
git commit -m "feat: HTTP API（search/card/get/snippets）"
```

---

### Task 8: 检索评测器（eval + golden queries）

**Files:**
- Create: `seckb/eval.py`
- Create: `tests/eval/golden_queries.yaml`
- Modify: `seckb/cli.py`（追加 `eval` 命令）
- Create: `tests/test_eval.py`
- Modify: `tests/test_cli_v3.py`（追加 CLI eval 用例）

- [ ] **Step 1: 写失败测试**

`tests/test_eval.py`：

```python
from pathlib import Path

from seckb.eval import EvalCase, load_cases, run_eval
from seckb.pipeline.importer import import_file
from seckb.retrieval import HybridRetriever


def test_load_cases(tmp_path: Path):
    path = tmp_path / "cases.yaml"
    path.write_text("- query: fastjson\n  expect_any: [fastjson]\n", encoding="utf-8")
    cases = load_cases(path)
    assert cases == [EvalCase(query="fastjson", expect_any=["fastjson"], type=None)]


def test_run_eval_counts_hits(kb, tmp_path: Path):
    src = tmp_path / "a.md"
    src.write_text("# fastjson 反序列化\n\n利用记录。", encoding="utf-8")
    import_file(kb.conn, kb.settings, src)
    retriever = HybridRetriever(kb.conn, kb.settings)
    cases = [
        EvalCase(query="fastjson", expect_any=["fastjson"]),
        EvalCase(query="fastjson", expect_any=["绝不匹配xyz"]),
    ]
    report = run_eval(retriever, cases)
    assert report.total == 2
    assert report.passed == 1
    assert report.details[0].passed is True
    assert report.details[1].passed is False
    assert report.hit_rate == 0.5


def test_default_golden_queries_file_is_valid():
    from seckb.eval import DEFAULT_CASES_PATH

    cases = load_cases(DEFAULT_CASES_PATH)
    assert len(cases) >= 10
    for case in cases:
        assert case.query and case.expect_any
```

追加到 `tests/test_cli_v3.py` 末尾：

```python
def test_cli_eval(tmp_path: Path):
    cfg = write_config(tmp_path)
    runner.invoke(app, ["--config", str(cfg), "init"])
    import_post(tmp_path, cfg, "# 永恒之蓝复现\n\nMS17-010 利用记录。")
    cases = tmp_path / "cases.yaml"
    cases.write_text("- query: 永恒之蓝\n  expect_any: [永恒之蓝]\n", encoding="utf-8")
    result = runner.invoke(app, ["--config", str(cfg), "eval", "--cases", str(cases)])
    assert result.exit_code == 0
    assert "命中率" in result.output
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_eval.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.eval'`

- [ ] **Step 3: 写最小实现**

`seckb/eval.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from seckb.config import REPO_ROOT
from seckb.retrieval import HybridRetriever

DEFAULT_CASES_PATH = REPO_ROOT / "tests" / "eval" / "golden_queries.yaml"


@dataclass
class EvalCase:
    query: str
    expect_any: list[str]
    type: str | None = None


@dataclass
class EvalDetail:
    query: str
    passed: bool
    top_titles: list[str]
    degraded: list[str]


@dataclass
class EvalReport:
    total: int = 0
    passed: int = 0
    details: list[EvalDetail] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def load_cases(path: Path) -> list[EvalCase]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    return [
        EvalCase(
            query=str(entry["query"]),
            expect_any=[str(item) for item in entry.get("expect_any") or []],
            type=entry.get("type"),
        )
        for entry in data
    ]


def _matches(case: EvalCase, title: str, tags: list[str]) -> bool:
    haystack = f"{title} {' '.join(tags)}".lower()
    return any(expectation.lower() in haystack for expectation in case.expect_any)


def run_eval(retriever: HybridRetriever, cases: list[EvalCase], *, top: int = 5) -> EvalReport:
    report = EvalReport(total=len(cases))
    for case in cases:
        response = retriever.search(case.query, asset_type=case.type, limit=top)
        passed = any(_matches(case, item.title, item.tags) for item in response.results)
        if passed:
            report.passed += 1
        report.details.append(
            EvalDetail(
                query=case.query,
                passed=passed,
                top_titles=[item.title for item in response.results],
                degraded=response.degraded,
            )
        )
    return report
```

`tests/eval/golden_queries.yaml`：

```yaml
- query: "fastjson 反序列化利用"
  expect_any: ["fastjson"]
- query: "Windows 内核提权"
  expect_any: ["windows-kernel-exploits", "提权", "privilege"]
- query: "Log4Shell 漏洞利用"
  expect_any: ["CVE-2021-44228", "log4j"]
- query: "永恒之蓝 MS17-010"
  expect_any: ["永恒之蓝", "MS17-010", "CVE-2017-0144"]
- query: "Spring 框架漏洞"
  expect_any: ["spring"]
- query: "nmap 端口扫描命令"
  expect_any: ["nmap"]
- query: "sqlmap 注入工具"
  expect_any: ["sqlmap"]
- query: "容器逃逸"
  expect_any: ["docker", "kubernetes", "逃逸", "escape"]
- query: "命令注入 getshell"
  expect_any: ["RCE", "注入", "execution", "getshell"]
- query: "Adobe Flash 远程代码执行"
  expect_any: ["flash", "CVE-2016-4117"]
```

`seckb/cli.py` 追加命令：

```python
@app.command()
def eval(
    ctx: typer.Context,
    top: int = typer.Option(5, "--top"),
    cases: Path = typer.Option(None, "--cases"),
) -> None:
    from seckb.eval import DEFAULT_CASES_PATH, load_cases, run_eval

    settings: Settings = ctx.obj
    conn = _open(settings)
    retriever = build_retriever(conn, settings)
    path = Path(cases) if cases else DEFAULT_CASES_PATH
    report = run_eval(retriever, load_cases(path), top=top)
    table = Table(title=f"检索评测（命中 {report.passed}/{report.total}）")
    table.add_column("查询", max_width=30)
    table.add_column("结果", width=6)
    table.add_column("Top 命中", max_width=60)
    for detail in report.details:
        table.add_row(detail.query, "通过" if detail.passed else "未中", " | ".join(detail.top_titles[:3]))
    console.print(table)
    console.print(f"命中率：{report.hit_rate:.0%}")
    conn.close()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_eval.py tests/test_cli_v3.py -v`
Expected: 全过

- [ ] **Step 5: 提交**

```powershell
git add seckb/eval.py tests/eval/golden_queries.yaml tests/test_eval.py tests/test_cli_v3.py seckb/cli.py
git commit -m "feat: 检索评测器与渗透场景 golden queries"
```

---

### Task 9: 端到端验收与收尾

**Files:**
- Create: `tests/test_e2e_v3.py`
- Modify: 依据 ruff 输出最小修复

- [ ] **Step 1: 写端到端测试**

`tests/test_e2e_v3.py`：

```python
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
```

- [ ] **Step 2: 运行全量测试与 ruff**

Run:
```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check seckb tests
```
Expected: 全部通过、ruff 无错误；若有问题逐条最小修复后重跑。

- [ ] **Step 3: 真实知识库冒烟（执行期手动，需 Meili 与 Ollama 已启动）**

```powershell
$env:MEILI_MASTER_KEY = [Environment]::GetEnvironmentVariable('MEILI_MASTER_KEY','User')
.venv\Scripts\python.exe -m seckb eval
.venv\Scripts\python.exe -m seckb search "fastjson 反序列化利用" -n 3
```
Expected: `eval` 命中率 ≥ 8/10（未中的条目记录为后续补采方向）；`search` 返回三路融合结果且无降级提示。

- [ ] **Step 4: 提交**

```powershell
git add tests/test_e2e_v3.py seckb/ tests/
git commit -m "test: P1c 端到端验收；融合检索与 Agent 接口完成"
```

---

## Agent 接线手册（执行完成后使用）

**渗透 agent 通过 MCP（stdio）接入**，以 opencode 为例（`opencode.json`）：

```json
{
  "mcp": {
    "seckb": {
      "type": "local",
      "command": ["D:\\HZR_PROJECTS\\seckb\\.venv\\Scripts\\python.exe", "-m", "seckb", "mcp"]
    }
  }
}
```

启动后 agent 可用四个工具：`kb_search`（混合检索）→ `kb_card`（看卡片）→ `kb_get`（按 token 预算取正文）→ `kb_snippets`（找命令/载荷）。推荐调用顺序：先 search 拿候选，用卡片判断相关度，再 get 或 snippets 深入。

**HTTP 方式**（任何语言）：

```powershell
.venv\Scripts\python.exe -m seckb serve --port 8011
# GET /search?q=fastjson&limit=5
# GET /card/123
# GET /get/123?max_tokens=1500&section=利用
# GET /snippets?tool=nmap&kind=oneliner
```

## 本计划明确的取舍（YAGNI）

- 融合只用 RRF，不引入 rerank 模型（后续需要再评估）
- HTTP 无鉴权（仅监听 127.0.0.1），MCP 只做 stdio，不做 SSE/HTTP 传输
- snippets 检索用 LIKE（当前 367 条量级足够；上万条后再上 FTS）
- 评测集是"诊断仪表"而非常规测试门禁：未中用例作为补采与调参方向
- 不实现 agent 查询日志落库（`queries` 表留到 P2 质量闭环）


