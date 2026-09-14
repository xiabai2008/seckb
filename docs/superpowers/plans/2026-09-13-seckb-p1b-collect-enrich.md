# seckb P1b：采集与富化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 P1a 数据管线上补齐采集与富化能力：T1 连接器（RSS/GitHub/NVD/KEV/ExploitDB/Vulhub）自动采集 → 增量游标 → 云端 LLM 富化（知识卡片/标签/实体/片段）→ 本地 bge-m3 向量化（Ollama）→ Meilisearch 索引 → 定时守护。

**Architecture:** 连接器实现统一接口 `fetch(cursor) -> (items, new_cursor)`，经 `ingest_items` 复用 P1a 的导入管线入库；富化走 SQLite `jobs` 异步队列，LLM 通过 OpenAI 兼容接口（默认 DeepSeek）；向量走 Ollama HTTP（bge-m3）+ LanceDB；关键词索引走 Meilisearch HTTP。所有外部依赖在测试中通过 `httpx.MockTransport` 与 Fake 实现隔离，无网络测试。

**Tech Stack:** Python 3.12、httpx、feedparser、APScheduler、LanceDB、Ollama（bge-m3）、Meilisearch、pytest、ruff

**环境约定：** 所有命令在 `D:\HZR_PROJECTS\seckb` 执行，使用 `.venv\Scripts\python.exe`。本计划不实现 MCP/HTTP 接口与 RRF 融合（属 P1c）。

---

## 文件结构（本计划结束时）

```
seckb/
├── config/
│   ├── sources.yaml         # 连接器清单与参数
│   ├── enrich.yaml          # LLM/向量/Meili 配置
│   └── schedule.yaml        # 采集周期
├── seckb/
│   ├── net.py               # httpx 客户端与带重试的 fetch_json/text/bytes
│   ├── collect.py           # 采集编排（游标、runs 日志）
│   ├── daemon.py            # APScheduler 守护
│   ├── connectors/
│   │   ├── __init__.py      # build_connector 注册表
│   │   ├── base.py          # RawItem、Connector 协议
│   │   ├── rss.py github.py nvd.py kev.py exploitdb.py vulhub.py
│   ├── pipeline/
│   │   ├── entities.py      # link_entity（从 importer 外移）
│   │   ├── ingest.py        # RawItem → import_file 管线
│   │   └── importer.py      # 扩展 source 元数据与目录路由
│   ├── enrich/
│   │   ├── llm.py parser.py prompts.py queue.py
│   └── indexer/
│       ├── vectors.py       # OllamaEmbedder + LanceDB
│       └── meili.py         # Meilisearch 客户端与文档构建
└── tests/                   # 新增 ~12 个测试文件
```

核心接口约定（P1c 依赖）：

- `collect_all(conn, settings, only=None) -> list[RunReport]`
- `build_connector(name, config, client) -> Connector`
- `process_jobs(conn, settings, provider, limit=10) -> QueueReport`
- `index_asset(conn, settings, embedder, asset_id)` / `search_vectors(settings, embedder, query, limit)`
- `build_doc(conn, asset_id) -> dict` / `MeiliClient`

---

### Task 1: 依赖与配置扩展

**Files:**
- Modify: `pyproject.toml`（dependencies 追加）
- Modify: `seckb/config.py`（Settings 增加 sources/enrich/schedule）
- Create: `config/sources.yaml`、`config/enrich.yaml`、`config/schedule.yaml`
- Modify: `tests/test_config.py`（追加用例）

- [ ] **Step 1: 写失败测试（追加到 `tests/test_config.py` 末尾）**

```python
def test_load_settings_reads_sources_enrich_schedule(tmp_path: Path):
    (tmp_path / "settings.yaml").write_text("kb_root: D:/KB2\n", encoding="utf-8")
    (tmp_path / "sources.yaml").write_text(
        "sources:\n  rss:\n    type: rss\n    feeds: [https://example.com/feed]\n",
        encoding="utf-8",
    )
    (tmp_path / "enrich.yaml").write_text(
        "provider:\n  model: deepseek-chat\nqueue:\n  max_attempts: 3\n",
        encoding="utf-8",
    )
    (tmp_path / "schedule.yaml").write_text(
        'collect:\n  rss: "0 */6 * * *"\nenrich:\n  every_minutes: 10\n',
        encoding="utf-8",
    )
    settings = load_settings(tmp_path)
    assert settings.sources["rss"]["type"] == "rss"
    assert settings.enrich["provider"]["model"] == "deepseek-chat"
    assert settings.schedule["collect"]["rss"] == "0 */6 * * *"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: FAIL，`AttributeError: 'Settings' object has no attribute 'sources'`

- [ ] **Step 3: 写最小实现**

`pyproject.toml` 的 `dependencies` 追加四行（放在 `"rich>=13.7",` 之后）：

```toml
    "httpx>=0.27",
    "feedparser>=6.0",
    "apscheduler>=3.10",
    "lancedb>=0.15",
```

`seckb/config.py` 完整替换为：

```python
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"
DEFAULT_KB_ROOT = Path("D:/SecurityKB")


@dataclass
class Settings:
    kb_root: Path
    config_dir: Path = DEFAULT_CONFIG_DIR
    taxonomy: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    enrich: dict = field(default_factory=dict)
    schedule: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.kb_root / "meta" / "catalog.db"


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_settings(config_dir: Path | None = None) -> Settings:
    env_dir = os.environ.get("SECKB_CONFIG")
    cfg_dir = Path(env_dir) if env_dir else Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    kb_root = Path(os.environ.get("SECKB_ROOT", DEFAULT_KB_ROOT))

    data = _read_yaml(cfg_dir / "settings.yaml")
    if data.get("kb_root"):
        kb_root = Path(data["kb_root"])

    return Settings(
        kb_root=kb_root,
        config_dir=cfg_dir,
        taxonomy=_read_yaml(cfg_dir / "taxonomy.yaml"),
        sources=_read_yaml(cfg_dir / "sources.yaml").get("sources", {}),
        enrich=_read_yaml(cfg_dir / "enrich.yaml"),
        schedule=_read_yaml(cfg_dir / "schedule.yaml"),
    )
```

`config/sources.yaml`：

```yaml
sources:
  rss:
    type: rss
    feeds:
      - https://www.freebuf.com/feed
      - https://api.anquanke.com/data/v1/rss
      - https://bbs.kanxue.com/rss.xml
      - https://feeds.feedburner.com/TheHackersNews
      - https://www.bleepingcomputer.com/feed/
      - https://kitploit.com/feeds/posts/default
  github:
    type: github
    search_queries:
      - "topic:security stars:>1000"
      - "topic:pentest stars:>500"
    awesome_repos:
      - sbilly/awesome-security
      - enaqx/awesome-pentest
      - qazbnm456/awesome-web-security
  nvd:
    type: nvd
    days_back: 7
    max_pages: 5
  kev:
    type: kev
  exploitdb:
    type: exploitdb
    max_rows: 500
  vulhub:
    type: vulhub
```

`config/enrich.yaml`：

```yaml
provider:
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat
  api_key_env: DEEPSEEK_API_KEY
  temperature: 0.2
  max_tokens: 1600
queue:
  max_assets_per_run: 10
  max_input_tokens: 6000
  max_attempts: 3
embedding:
  provider: ollama
  base_url: http://127.0.0.1:11434
  model: bge-m3
meili:
  base_url: http://127.0.0.1:7700
  api_key_env: MEILI_MASTER_KEY
```

`config/schedule.yaml`：

```yaml
collect:
  rss: "0 */6 * * *"
  nvd: "0 3 * * *"
  kev: "30 3 * * *"
  github: "0 4 * * 1"
  exploitdb: "0 5 * * *"
  vulhub: "0 5 * * 0"
enrich:
  every_minutes: 10
```

- [ ] **Step 4: 安装新依赖并跑测试**

Run:
```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest tests/test_config.py -v
```
（pip 安装用 bash timeout 600000；若 lancedb 安装失败，停止并报告，不要换库）
Expected: `3 passed`

- [ ] **Step 5: 提交**

```powershell
git add pyproject.toml seckb/config.py config/ tests/test_config.py
git commit -m "feat: P1b 依赖与配置扩展（sources/enrich/schedule）"
```

---

### Task 2: 迁移 0002（采集/富化/扩展表）

**Files:**
- Create: `seckb/db/migrations/0002_collect_enrich.sql`
- Create: `tests/test_db_v2.py`
- Modify: `tests/test_db.py`（P1a 的 `user_version == 1` 断言改为 2，共 3 处）

- [ ] **Step 1: 写失败测试**

`tests/test_db_v2.py`：

```python
import sqlite3

import pytest


def test_user_version_is_2(kb):
    assert kb.conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_new_tables_exist(kb):
    names = {
        row["name"]
        for row in kb.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for expected in {"sources", "runs", "jobs", "cards", "repos", "cves"}:
        assert expected in names


def test_assets_has_source_id(kb):
    columns = {row["name"] for row in kb.conn.execute("PRAGMA table_info(assets)")}
    assert "source_id" in columns


def test_source_id_unique_per_source(kb):
    kb.conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at, source, source_id)"
        " VALUES('post','a','s1','markdown','now','rss','e1')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        kb.conn.execute(
            "INSERT INTO assets(type, title, sha256, format, imported_at, source, source_id)"
            " VALUES('post','b','s2','markdown','now','rss','e1')"
        )
    kb.conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at, source, source_id)"
        " VALUES('post','c','s3','markdown','now','manual',NULL)"
    )
    kb.conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at, source, source_id)"
        " VALUES('post','d','s4','markdown','now','manual',NULL)"
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_db_v2.py -v`
Expected: FAIL，`assert 1 == 2`

- [ ] **Step 3: 写迁移文件**

`seckb/db/migrations/0002_collect_enrich.sql`：

```sql
ALTER TABLE assets ADD COLUMN source_id TEXT;
CREATE UNIQUE INDEX idx_assets_source_id ON assets(source, source_id)
  WHERE source_id IS NOT NULL;

CREATE TABLE sources (
  name TEXT PRIMARY KEY,
  last_cursor TEXT,
  last_run_at TEXT,
  etag TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  health TEXT NOT NULL DEFAULT 'ok'
);

CREATE TABLE runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  fetched INTEGER NOT NULL DEFAULT 0,
  imported INTEGER NOT NULL DEFAULT 0,
  skipped INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0,
  error TEXT
);

CREATE TABLE jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE INDEX idx_jobs_status ON jobs(status);

CREATE TABLE cards (
  asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
  summary TEXT NOT NULL,
  key_takeaways TEXT NOT NULL DEFAULT '[]',
  card_json TEXT NOT NULL,
  model TEXT,
  generated_at TEXT NOT NULL
);

CREATE TABLE repos (
  asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
  owner TEXT,
  name TEXT,
  stars INTEGER,
  forks INTEGER,
  language TEXT,
  topics TEXT,
  clone_url TEXT,
  license TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  last_commit TEXT
);

CREATE TABLE cves (
  asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
  cve_id TEXT,
  cvss REAL,
  cwe TEXT,
  affected TEXT,
  poc_refs TEXT,
  in_kev INTEGER NOT NULL DEFAULT 0
);
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_db_v2.py tests/test_db.py -v`
Expected: `9 passed`（4 个新用例 + 5 个既有用例）；再跑全量 `pytest -q` 确认既有测试不回归（应为 55 passed）

> 执行记录（2026-09-13）：P1a 的 `tests/test_db.py` 中 3 处 `user_version == 1` 断言需同步改为 `2`（迁移 0002 生效后版本号为 2），这是计划外的必要修正，已实施。

- [ ] **Step 5: 提交**

```powershell
git add seckb/db/migrations/0002_collect_enrich.sql tests/test_db_v2.py
git commit -m "feat: 迁移 0002（sources/runs/jobs/cards/repos/cves）"
```

---

### Task 3: HTTP 工具（重试与可注入 transport）

**Files:**
- Create: `seckb/net.py`
- Create: `tests/test_net.py`

- [ ] **Step 1: 写失败测试**

`tests/test_net.py`：

```python
import httpx
import pytest

from seckb.net import FetchError, build_client, fetch_json


def test_fetch_json_retries_transport_error():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json={"ok": True})

    client = build_client(transport=httpx.MockTransport(handler))
    data = fetch_json(client, "https://example.com/api", sleep=lambda _: None)
    assert data == {"ok": True}
    assert len(calls) == 2


def test_fetch_json_retries_503_then_success():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"n": len(calls)})

    client = build_client(transport=httpx.MockTransport(handler))
    assert fetch_json(client, "https://example.com/x", sleep=lambda _: None) == {"n": 2}


def test_fetch_json_raises_after_attempts():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("always down")

    client = build_client(transport=httpx.MockTransport(handler))
    with pytest.raises(FetchError):
        fetch_json(client, "https://example.com/y", attempts=3, sleep=lambda _: None)


def test_fetch_json_http_400_is_fetch_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="nope")

    client = build_client(transport=httpx.MockTransport(handler))
    with pytest.raises(FetchError):
        fetch_json(client, "https://example.com/z", sleep=lambda _: None)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_net.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.net'`

- [ ] **Step 3: 写最小实现**

`seckb/net.py`：

```python
from __future__ import annotations

import time
from collections.abc import Callable

import httpx

USER_AGENT = "seckb/0.2 (+local knowledge base)"
RETRY_STATUS = {429, 500, 502, 503, 504}
BACKOFF_BASE = 0.5


class FetchError(Exception):
    pass


def build_client(
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float = 20.0,
    headers: dict | None = None,
) -> httpx.Client:
    merged = {"User-Agent": USER_AGENT}
    if headers:
        merged.update(headers)
    return httpx.Client(
        timeout=timeout, headers=merged, transport=transport, follow_redirects=True
    )


def _request(
    client: httpx.Client,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url, params=params, headers=headers)
            if response.status_code in RETRY_STATUS and attempt < attempts:
                sleep(BACKOFF_BASE * 2**attempt)
                continue
            if response.status_code >= 400:
                raise FetchError(f"GET {url} -> HTTP {response.status_code}")
            return response
        except httpx.TransportError as exc:
            last_error = exc
            if attempt < attempts:
                sleep(BACKOFF_BASE * 2**attempt)
                continue
            raise FetchError(f"GET {url} failed: {exc}") from exc
    raise FetchError(f"GET {url} retries exhausted: {last_error}")


def fetch_json(
    client: httpx.Client,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    return _request(
        client, url, params=params, headers=headers, attempts=attempts, sleep=sleep
    ).json()


def fetch_text(
    client: httpx.Client,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    return _request(
        client, url, params=params, headers=headers, attempts=attempts, sleep=sleep
    ).text


def fetch_bytes(
    client: httpx.Client,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    return _request(
        client, url, params=params, headers=headers, attempts=attempts, sleep=sleep
    ).content
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_net.py -v`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/net.py tests/test_net.py
git commit -m "feat: HTTP 工具（重试/可注入 transport）"
```

---

### Task 4: 实体外移、导入器扩展与 ingest 管线

**Files:**
- Create: `seckb/pipeline/entities.py`
- Create: `seckb/connectors/__init__.py`（空）、`seckb/connectors/base.py`
- Create: `seckb/pipeline/ingest.py`
- Modify: `seckb/pipeline/importer.py`
- Create: `tests/test_ingest.py`

- [ ] **Step 1: 写失败测试**

`tests/test_ingest.py`：

```python
from pathlib import Path

from seckb.connectors.base import RawItem
from seckb.pipeline.entities import link_entity
from seckb.pipeline.importer import import_file
from seckb.pipeline.ingest import ingest_items


def test_link_entity_reuses_entity(kb):
    kb.conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at) VALUES('post','t','x1','markdown','now')"
    )
    kb.conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at) VALUES('post','t2','x2','markdown','now')"
    )
    a = link_entity(kb.conn, 1, "tool", "nmap")
    b = link_entity(kb.conn, 2, "tool", "NMAP")
    assert a == b


def test_import_records_source_metadata(kb, tmp_path: Path):
    src = tmp_path / "n.md"
    src.write_text("# 测试源元数据\n\n内容。", encoding="utf-8")
    report = import_file(
        kb.conn,
        kb.settings,
        src,
        source="rss",
        source_url="https://example.com/post/1",
        published_at="2026-09-01T08:00:00",
        source_id="https://example.com/post/1",
    )
    row = kb.conn.execute("SELECT * FROM assets WHERE id = ?", (report.asset_id,)).fetchone()
    assert row["source"] == "rss"
    assert row["source_url"] == "https://example.com/post/1"
    assert row["published_at"] == "2026-09-01T08:00:00"
    assert row["source_id"] == "https://example.com/post/1"


def test_import_routes_repo_and_cve(kb, tmp_path: Path):
    repo_src = tmp_path / "repo.md"
    repo_src.write_text("# owner/name\n\n一个安全工具仓库。", encoding="utf-8")
    report = import_file(
        kb.conn,
        kb.settings,
        repo_src,
        asset_type="repo",
        source="github",
        source_id="repo:owner/name",
        extra={"owner": "owner", "name": "name", "stars": 1200, "topics": ["security"]},
    )
    row = kb.conn.execute("SELECT * FROM assets WHERE id = ?", (report.asset_id,)).fetchone()
    assert row["path"].startswith("repos/")
    repo_row = kb.conn.execute(
        "SELECT * FROM repos WHERE asset_id = ?", (report.asset_id,)
    ).fetchone()
    assert repo_row["stars"] == 1200

    cve_src = tmp_path / "cve.md"
    cve_src.write_text("# CVE-2026-0001\n\n测试漏洞。", encoding="utf-8")
    report2 = import_file(
        kb.conn,
        kb.settings,
        cve_src,
        asset_type="cve",
        source="nvd",
        source_id="CVE-2026-0001",
        published_at="2026-08-20T00:00:00.000",
        extra={"cvss": 9.8, "cwe": "CWE-79", "poc_refs": ["https://example.com/poc"]},
    )
    row2 = kb.conn.execute("SELECT * FROM assets WHERE id = ?", (report2.asset_id,)).fetchone()
    assert row2["path"].startswith("vulndb/2026/")
    cve_row = kb.conn.execute(
        "SELECT * FROM cves WHERE asset_id = ?", (report2.asset_id,)
    ).fetchone()
    assert cve_row["cvss"] == 9.8
    assert cve_row["in_kev"] == 0


def test_ingest_creates_asset_and_job(kb):
    items = [
        RawItem(
            source_id="https://example.com/a",
            title="测试帖子",
            content="这是来自 RSS 的正文，包含 nmap 关键词。",
            url="https://example.com/a",
            published_at="2026-09-02T00:00:00",
        )
    ]
    stats = ingest_items(kb.conn, kb.settings, items, source="rss")
    assert stats.imported == 1
    row = kb.conn.execute(
        "SELECT * FROM assets WHERE source_id = 'https://example.com/a'"
    ).fetchone()
    assert row["source"] == "rss"
    job = kb.conn.execute("SELECT * FROM jobs WHERE asset_id = ?", (row["id"],)).fetchone()
    assert job["kind"] == "summary"
    assert job["status"] == "pending"


def test_ingest_dedupes_by_source_id(kb):
    item = RawItem(source_id="dup-1", title="重复", content="内容。", url=None)
    assert ingest_items(kb.conn, kb.settings, [item], source="rss").imported == 1
    assert ingest_items(kb.conn, kb.settings, [item], source="rss").skipped == 1
    count = kb.conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    assert count == 1


def test_ingest_marks_existing_cve_in_kev(kb):
    src_path = kb.root / "meta" / "tmp" / "cve-seed.md"
    src_path.parent.mkdir(parents=True, exist_ok=True)
    src_path.write_text("# CVE-2021-44228\n\nLog4Shell。", encoding="utf-8")
    report = import_file(
        kb.conn,
        kb.settings,
        src_path,
        asset_type="cve",
        source="nvd",
        source_id="CVE-2021-44228",
    )
    kev_item = RawItem(
        source_id="CVE-2021-44228",
        title="CVE-2021-44228 KEV",
        content="在野利用。",
        asset_type="cve",
        extra={"in_kev": True, "cve_id": "CVE-2021-44228"},
    )
    stats = ingest_items(kb.conn, kb.settings, [kev_item], source="kev")
    assert stats.updated == 1
    assert stats.imported == 0
    row = kb.conn.execute(
        "SELECT * FROM cves WHERE asset_id = ?", (report.asset_id,)
    ).fetchone()
    assert row["in_kev"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ingest.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.pipeline.entities'`

- [ ] **Step 3: 写最小实现**

`seckb/pipeline/entities.py`：

```python
from __future__ import annotations

import sqlite3


def link_entity(conn: sqlite3.Connection, asset_id: int, kind: str, name: str) -> int:
    canonical = name.lower()
    row = conn.execute(
        "SELECT id FROM entities WHERE kind = ? AND canonical = ?", (kind, canonical)
    ).fetchone()
    if row:
        entity_id = row["id"]
    else:
        cursor = conn.execute(
            "INSERT INTO entities(kind, name, canonical) VALUES(?,?,?)", (kind, name, canonical)
        )
        entity_id = cursor.lastrowid
    conn.execute(
        "INSERT OR IGNORE INTO asset_entities(asset_id, entity_id) VALUES(?,?)",
        (asset_id, entity_id),
    )
    return entity_id
```

`seckb/connectors/__init__.py`（先写空文件，Task 10 再填注册表）

`seckb/connectors/base.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class RawItem:
    source_id: str
    title: str
    content: str
    asset_type: str = "post"
    url: str | None = None
    published_at: str | None = None
    extra: dict = field(default_factory=dict)


class Connector(Protocol):
    name: str

    def fetch(self, cursor: str | None) -> tuple[list[RawItem], str | None]: ...
```

修改 `seckb/pipeline/importer.py`（四处替换）：

1）导入区与函数外移：在

```python
from seckb.pipeline.dedupe import find_by_sha256, find_near_duplicate
```

之后加一行

```python
from seckb.pipeline.entities import link_entity
```

删除文件中 `_link_entity` 函数定义，并把三处 `_link_entity(conn, asset_id, ...)` 调用改为 `link_entity(conn, asset_id, ...)`。

2）新增路由辅助（放在 `_first_h1` 之后）：

```python
def _target_dir(kind: str, direction: str, lang: str, published_at: str | None) -> Path:
    if kind == "book":
        return Path("books") / direction
    if kind == "cve":
        year = published_at[:4] if published_at and published_at[:4].isdigit() else "misc"
        return Path("vulndb") / year
    if kind == "repo":
        return Path("repos")
    if kind == "writeup":
        return Path("ctf")
    return Path("posts") / lang
```

3）`import_file` 签名与源元数据。签名改为：

```python
def import_file(
    conn: sqlite3.Connection,
    settings: Settings,
    src: Path,
    *,
    asset_type: str | None = None,
    source: str = "manual",
    source_url: str | None = None,
    published_at: str | None = None,
    source_id: str | None = None,
    extra: dict | None = None,
) -> ImportReport:
```

`rel_dir` 计算替换为：

```python
    rel_dir = _target_dir(kind, direction, lang, published_at)
```

INSERT 语句与参数替换为：

```python
    cursor = conn.execute(
        """
        INSERT INTO assets(type, title, lang, source, source_url, path, md_path,
                           sha256, simhash, size, format, published_at, imported_at,
                           tags, category, status, source_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            kind,
            title,
            lang,
            source,
            source_url,
            orig_rel,
            md_rel,
            sha,
            to_signed64(simhash64(result.markdown)),
            orig_size,
            result.source_type,
            published_at,
            now,
            "[]",
            direction,
            "ok",
            source_id,
        ),
    )
```

4）扩展表写入（放在 `if kind == "book":` 块之后、`fts.index_asset` 之前）：

```python
    if kind == "repo" and extra and extra.get("owner"):
        conn.execute(
            """
            INSERT INTO repos(asset_id, owner, name, stars, forks, language, topics,
                              clone_url, license, archived, last_commit)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                asset_id,
                extra.get("owner"),
                extra.get("name"),
                extra.get("stars"),
                extra.get("forks"),
                extra.get("language"),
                json.dumps(extra.get("topics") or [], ensure_ascii=False),
                extra.get("clone_url"),
                extra.get("license"),
                1 if extra.get("archived") else 0,
                extra.get("last_commit"),
            ),
        )
    if kind == "cve":
        data = extra or {}
        conn.execute(
            """
            INSERT OR REPLACE INTO cves(asset_id, cve_id, cvss, cwe, affected, poc_refs, in_kev)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                asset_id,
                data.get("cve_id"),
                data.get("cvss"),
                data.get("cwe"),
                data.get("affected"),
                json.dumps(data.get("poc_refs") or [], ensure_ascii=False),
                1 if data.get("in_kev") else 0,
            ),
        )
```

`seckb/pipeline/ingest.py`：

```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from seckb.config import Settings
from seckb.connectors.base import RawItem
from seckb.pipeline.importer import import_file
from seckb.utils.hashing import slugify


@dataclass
class IngestStats:
    imported: int = 0
    duplicated: int = 0
    skipped: int = 0
    updated: int = 0


def _find_by_source_id(conn: sqlite3.Connection, source: str, source_id: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM assets WHERE source = ? AND source_id = ?", (source, source_id)
    ).fetchone()
    return row["id"] if row else None


def _find_cve_asset(conn: sqlite3.Connection, source_id: str) -> int | None:
    row = conn.execute(
        """SELECT a.id FROM assets a JOIN cves c ON c.asset_id = a.id
           WHERE a.source_id = ? ORDER BY a.id LIMIT 1""",
        (source_id,),
    ).fetchone()
    return row["id"] if row else None


def ingest_items(
    conn: sqlite3.Connection,
    settings: Settings,
    items: list[RawItem],
    *,
    source: str = "unknown",
) -> IngestStats:
    stats = IngestStats()
    tmp_dir = settings.kb_root / "meta" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for item in items:
        if item.source_id and _find_by_source_id(conn, source, item.source_id):
            stats.skipped += 1
            continue
        if item.extra.get("in_kev") and item.source_id:
            asset_id = _find_cve_asset(conn, item.source_id)
            if asset_id is not None:
                conn.execute("UPDATE cves SET in_kev = 1 WHERE asset_id = ?", (asset_id,))
                conn.commit()
                stats.updated += 1
                continue
        content = item.content
        if not content.lstrip().startswith("# "):
            content = f"# {item.title}\n\n{content}"
        tmp_path = tmp_dir / f"ingest-{slugify(item.source_id or item.title)}.md"
        tmp_path.write_text(content, encoding="utf-8")
        report = import_file(
            conn,
            settings,
            tmp_path,
            asset_type=item.asset_type,
            source=source,
            source_url=item.url,
            published_at=item.published_at,
            source_id=item.source_id,
            extra=item.extra,
        )
        if report.status == "imported" and report.asset_id is not None:
            conn.execute(
                "INSERT INTO jobs(asset_id, kind, status, created_at) VALUES(?, 'summary', 'pending', ?)",
                (report.asset_id, datetime.now(UTC).isoformat(timespec="seconds")),
            )
            conn.commit()
            stats.imported += 1
        else:
            stats.duplicated += 1
    return stats
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ingest.py tests/test_importer.py -v`
Expected: 全过；再跑全量 `pytest -q`（应为 61 passed）

- [ ] **Step 5: 提交**

```powershell
git add seckb/pipeline/entities.py seckb/pipeline/ingest.py seckb/pipeline/importer.py seckb/connectors/ tests/test_ingest.py
git commit -m "feat: 实体外移 + 导入器源元数据/路由 + ingest 管线"
```

---

### Task 5: RSS 连接器

**Files:**
- Create: `seckb/connectors/rss.py`
- Create: `tests/test_connector_rss.py`

- [ ] **Step 1: 写失败测试**

`tests/test_connector_rss.py`：

```python
import httpx

from seckb.connectors.rss import RSSConnector
from seckb.net import build_client

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>安全资讯</title>
<item>
  <title>Nmap 使用技巧</title>
  <link>https://example.com/nmap</link>
  <guid>https://example.com/nmap</guid>
  <pubDate>Mon, 01 Sep 2026 08:00:00 GMT</pubDate>
  <description>&lt;p&gt;使用 &lt;b&gt;nmap&lt;/b&gt; 扫描端口&lt;/p&gt;</description>
</item>
<item>
  <title>SQLMap 进阶</title>
  <link>https://example.com/sqlmap</link>
  <guid>https://example.com/sqlmap</guid>
  <description>sqlmap tamper 脚本说明</description>
</item>
</channel></rss>
"""


def test_rss_connector_parses_entries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=FEED, headers={"Content-Type": "application/rss+xml"})

    client = build_client(transport=httpx.MockTransport(handler))
    connector = RSSConnector("rss", ["https://example.com/feed"], client, sleep=lambda _: None)
    items, cursor = connector.fetch(None)
    assert len(items) == 2
    first = items[0]
    assert first.source_id == "https://example.com/nmap"
    assert first.title == "Nmap 使用技巧"
    assert "nmap" in first.content
    assert "<p>" not in first.content
    assert first.published_at is not None
    assert cursor is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_connector_rss.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.connectors.rss'`

- [ ] **Step 3: 写最小实现**

`seckb/connectors/rss.py`：

```python
from __future__ import annotations

import time
from collections.abc import Callable

import feedparser
import httpx

from seckb.connectors.base import RawItem
from seckb.net import fetch_bytes
from seckb.pipeline.normalize import html_to_markdown


class RSSConnector:
    def __init__(
        self,
        name: str,
        feeds: list[str],
        client: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.feeds = feeds
        self.client = client
        self.sleep = sleep

    def fetch(self, cursor: str | None) -> tuple[list[RawItem], str | None]:
        items: list[RawItem] = []
        for feed_url in self.feeds:
            raw = fetch_bytes(self.client, feed_url, sleep=self.sleep)
            parsed = feedparser.parse(raw)
            for entry in parsed.entries:
                link = (entry.get("link") or "").strip()
                source_id = (entry.get("id") or link).strip()
                if not source_id:
                    continue
                title = (entry.get("title") or link).strip()
                body = entry.get("summary") or entry.get("description") or ""
                if "<" in body:
                    _, body = html_to_markdown(body)
                items.append(
                    RawItem(
                        source_id=source_id,
                        title=title,
                        content=body.strip(),
                        asset_type="post",
                        url=link or None,
                        published_at=entry.get("published") or entry.get("updated"),
                        extra={"site": feed_url},
                    )
                )
        return items, cursor
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_connector_rss.py -v`
Expected: `1 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/connectors/rss.py tests/test_connector_rss.py
git commit -m "feat: RSS 连接器"
```

---

### Task 6: GitHub 连接器

**Files:**
- Create: `seckb/connectors/github.py`
- Create: `tests/test_connector_github.py`

- [ ] **Step 1: 写失败测试**

`tests/test_connector_github.py`：

```python
import httpx

from seckb.connectors.github import GitHubConnector
from seckb.net import build_client

SEARCH_JSON = {
    "items": [
        {
            "full_name": "owner/tool",
            "html_url": "https://github.com/owner/tool",
            "description": "A security tool",
            "stargazers_count": 1200,
            "forks_count": 100,
            "language": "Go",
            "topics": ["security", "scanner"],
            "clone_url": "https://github.com/owner/tool.git",
            "license": {"spdx_id": "MIT"},
            "archived": False,
            "pushed_at": "2026-09-01T00:00:00Z",
        }
    ]
}

README = """
# Awesome Security
- [tool](https://github.com/owner/tool)
- [another](https://github.com/owner/another)
- [self](https://github.com/awesome/list)
"""


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "/search/repositories" in url:
        return httpx.Response(200, json=SEARCH_JSON)
    if url.endswith("/README.md"):
        return httpx.Response(200, text=README)
    return httpx.Response(404, text="not found")


def make_connector():
    client = build_client(transport=httpx.MockTransport(handler))
    return GitHubConnector(
        "github",
        client,
        queries=["topic:security stars:>1000"],
        awesome_repos=["awesome/list"],
        sleep=lambda _: None,
    )


def test_github_search_items():
    items, cursor = make_connector().fetch(None)
    search_items = [i for i in items if i.source_id == "repo:owner/tool"]
    assert len(search_items) == 1
    item = search_items[0]
    assert item.asset_type == "repo"
    assert item.extra["stars"] == 1200
    assert item.extra["license"] == "MIT"
    assert item.extra["topics"] == ["security", "scanner"]
    assert cursor is None


def test_github_awesome_links_deduped_and_self_excluded():
    items, _ = make_connector().fetch(None)
    awesome_ids = sorted(i.source_id for i in items if i.source_id.startswith("awesome:"))
    assert awesome_ids == ["awesome:owner/another", "awesome:owner/tool"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_connector_github.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.connectors.github'`

- [ ] **Step 3: 写最小实现**

`seckb/connectors/github.py`：

```python
from __future__ import annotations

import os
import re
import time
from collections.abc import Callable

import httpx

from seckb.connectors.base import RawItem
from seckb.net import fetch_json, fetch_text

API_ROOT = "https://api.github.com"
RAW_ROOT = "https://raw.githubusercontent.com"
REPO_LINK_RE = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)")
RESERVED_OWNERS = {
    "features", "topics", "sponsors", "settings", "notifications", "explore",
    "marketplace", "apps", "about", "pricing", "login", "join", "orgs", "users",
}


def _repo_item(repo: dict) -> RawItem:
    full_name = repo["full_name"]
    description = repo.get("description") or ""
    topics = repo.get("topics") or []
    stars = repo.get("stargazers_count") or 0
    content = "\n".join(
        part
        for part in (
            description,
            "",
            f"- Stars: {stars}",
            f"- Language: {repo.get('language') or '未知'}",
            f"- Topics: {', '.join(topics)}" if topics else "",
            f"- 仓库地址: {repo.get('html_url')}",
        )
        if part != ""
    )
    owner, _, name = full_name.partition("/")
    return RawItem(
        source_id=f"repo:{full_name}",
        title=full_name,
        content=content,
        asset_type="repo",
        url=repo.get("html_url"),
        published_at=repo.get("pushed_at"),
        extra={
            "owner": owner,
            "name": name,
            "stars": stars,
            "forks": repo.get("forks_count"),
            "language": repo.get("language"),
            "topics": topics,
            "clone_url": repo.get("clone_url"),
            "license": (repo.get("license") or {}).get("spdx_id"),
            "archived": repo.get("archived"),
            "last_commit": repo.get("pushed_at"),
        },
    )


def _extract_repo_links(readme: str, exclude: str) -> set[str]:
    found: set[str] = set()
    for owner, name in REPO_LINK_RE.findall(readme):
        if owner.lower() in RESERVED_OWNERS:
            continue
        full_name = f"{owner}/{name}"
        if full_name.lower() == exclude.lower():
            continue
        found.add(full_name)
    return found


class GitHubConnector:
    def __init__(
        self,
        name: str,
        client: httpx.Client,
        *,
        queries: list[str] | None = None,
        awesome_repos: list[str] | None = None,
        per_page: int = 50,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.client = client
        self.queries = queries or []
        self.awesome_repos = awesome_repos or []
        self.per_page = per_page
        self.sleep = sleep

    def _headers(self) -> dict:
        token = os.environ.get("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def fetch(self, cursor: str | None) -> tuple[list[RawItem], str | None]:
        items: list[RawItem] = []
        for query in self.queries:
            data = fetch_json(
                self.client,
                f"{API_ROOT}/search/repositories",
                params={
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": self.per_page,
                },
                headers=self._headers(),
                sleep=self.sleep,
            )
            for repo in data.get("items", []):
                items.append(_repo_item(repo))
        for full_name in self.awesome_repos:
            readme = fetch_text(
                self.client,
                f"{RAW_ROOT}/{full_name}/HEAD/README.md",
                sleep=self.sleep,
            )
            for linked in sorted(_extract_repo_links(readme, full_name)):
                owner, _, name = linked.partition("/")
                url = f"https://github.com/{owner}/{name}"
                items.append(
                    RawItem(
                        source_id=f"awesome:{owner}/{name}",
                        title=f"{owner}/{name}",
                        content=f"来自 awesome 列表 {full_name} 的推荐仓库。\n\n- 仓库地址: {url}",
                        asset_type="repo",
                        url=url,
                        extra={
                            "owner": owner,
                            "name": name,
                            "topics": [],
                            "awesome_list": full_name,
                        },
                    )
                )
        return items, cursor
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_connector_github.py -v`
Expected: `2 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/connectors/github.py tests/test_connector_github.py
git commit -m "feat: GitHub 连接器（搜索 + awesome 列表）"
```

---

### Task 7: NVD 连接器

**Files:**
- Create: `seckb/connectors/nvd.py`
- Create: `tests/test_connector_nvd.py`

- [ ] **Step 1: 写失败测试**

`tests/test_connector_nvd.py`：

```python
import httpx

from seckb.connectors.nvd import NVDConnector
from seckb.net import build_client

NVD_JSON = {
    "resultsPerPage": 2,
    "startIndex": 0,
    "totalResults": 2,
    "vulnerabilities": [
        {
            "cve": {
                "id": "CVE-2026-0001",
                "published": "2026-09-01T00:00:00.000",
                "descriptions": [{"lang": "en", "value": "Test XSS vulnerability"}],
                "metrics": {"cvssMetricV31": [{"cvssData": {"baseScore": 9.8}}]},
                "weaknesses": [{"description": [{"value": "CWE-79"}]}],
                "references": [{"url": "https://example.com/advisory"}],
            }
        },
        {
            "cve": {
                "id": "CVE-2026-0002",
                "published": "2026-09-02T00:00:00.000",
                "descriptions": [{"lang": "en", "value": "Test RCE vulnerability"}],
                "references": [],
            }
        },
    ],
}

seen_params: list[dict] = []


def handler(request: httpx.Request) -> httpx.Response:
    seen_params.append(dict(request.url.params))
    return httpx.Response(200, json=NVD_JSON)


def test_nvd_parses_cves_and_cursor():
    client = build_client(transport=httpx.MockTransport(handler))
    connector = NVDConnector("nvd", client, days_back=7, sleep=lambda _: None)
    items, cursor = connector.fetch(None)
    assert len(items) == 2
    first = items[0]
    assert first.source_id == "CVE-2026-0001"
    assert first.asset_type == "cve"
    assert first.extra["cvss"] == 9.8
    assert first.extra["cwe"] == "CWE-79"
    assert "Test XSS vulnerability" in first.content
    assert "https://example.com/advisory" in first.content
    assert cursor and cursor.startswith("20")
    assert "lastModStartDate" in seen_params[0]


def test_nvd_uses_cursor_as_start():
    client = build_client(transport=httpx.MockTransport(handler))
    connector = NVDConnector("nvd", client, sleep=lambda _: None)
    seen_params.clear()
    connector.fetch("2026-09-01T00:00:00.000")
    assert seen_params[0]["lastModStartDate"] == "2026-09-01T00:00:00.000"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_connector_nvd.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.connectors.nvd'`

- [ ] **Step 3: 写最小实现**

`seckb/connectors/nvd.py`：

```python
from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from seckb.connectors.base import RawItem
from seckb.net import fetch_json

API_ROOT = "https://services.nvd.nist.gov/rest/json/cves/2.0"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.000"


def _cvss_score(cve: dict) -> float | None:
    metrics = cve.get("metrics") or {}
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(key) or []
        if entries:
            return (entries[0].get("cvssData") or {}).get("baseScore")
    return None


def _cwe(cve: dict) -> str | None:
    for weakness in cve.get("weaknesses") or []:
        for description in weakness.get("description") or []:
            value = description.get("value")
            if value and value.startswith("CWE-"):
                return value
    return None


def _description(cve: dict) -> str:
    for entry in cve.get("descriptions") or []:
        if entry.get("lang") == "en":
            return entry.get("value") or ""
    return ""


def _cve_item(vuln: dict) -> RawItem:
    cve = vuln["cve"]
    cve_id = cve["id"]
    description = _description(cve)
    score = _cvss_score(cve)
    cwe = _cwe(cve)
    references = [ref.get("url") for ref in cve.get("references") or [] if ref.get("url")]
    lines = [f"## {cve_id}", "", description, ""]
    if score is not None:
        lines.append(f"- CVSS: {score}")
    if cwe:
        lines.append(f"- CWE: {cwe}")
    if references:
        lines.extend(["", "### 参考链接", ""])
        lines.extend(f"- {url}" for url in references[:10])
    return RawItem(
        source_id=cve_id,
        title=cve_id,
        content="\n".join(lines),
        asset_type="cve",
        url=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
        published_at=cve.get("published"),
        extra={"cve_id": cve_id, "cvss": score, "cwe": cwe, "poc_refs": references},
    )


class NVDConnector:
    def __init__(
        self,
        name: str,
        client: httpx.Client,
        *,
        days_back: int = 7,
        max_pages: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.client = client
        self.days_back = days_back
        self.max_pages = max_pages
        self.sleep = sleep

    def _headers(self) -> dict:
        api_key = os.environ.get("NVD_API_KEY")
        return {"apiKey": api_key} if api_key else {}

    def fetch(self, cursor: str | None) -> tuple[list[RawItem], str | None]:
        end = datetime.now(UTC)
        start = cursor or (end - timedelta(days=self.days_back)).strftime(TIME_FORMAT)
        end_str = end.strftime(TIME_FORMAT)
        items: list[RawItem] = []
        start_index = 0
        for _ in range(self.max_pages):
            data = fetch_json(
                self.client,
                API_ROOT,
                params={
                    "lastModStartDate": start,
                    "lastModEndDate": end_str,
                    "resultsPerPage": 200,
                    "startIndex": start_index,
                },
                headers=self._headers(),
                sleep=self.sleep,
            )
            for vuln in data.get("vulnerabilities", []):
                items.append(_cve_item(vuln))
            page_size = data.get("resultsPerPage") or 200
            start_index += page_size
            if start_index >= (data.get("totalResults") or 0):
                break
        return items, end_str
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_connector_nvd.py -v`
Expected: `2 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/connectors/nvd.py tests/test_connector_nvd.py
git commit -m "feat: NVD 连接器（增量游标 + CVSS/CWE/参考）"
```

---

### Task 8: KEV 与 ExploitDB 连接器

**Files:**
- Create: `seckb/connectors/kev.py`
- Create: `seckb/connectors/exploitdb.py`
- Create: `tests/test_connectors_cve_feeds.py`

- [ ] **Step 1: 写失败测试**

`tests/test_connectors_cve_feeds.py`：

```python
import httpx

from seckb.connectors.exploitdb import ExploitDBConnector
from seckb.connectors.kev import KEVConnector
from seckb.net import build_client

KEV_JSON = {
    "vulnerabilities": [
        {
            "cveID": "CVE-2021-44228",
            "vendorProject": "Apache",
            "product": "Log4j",
            "vulnerabilityName": "Log4Shell",
            "dateAdded": "2021-12-10",
            "shortDescription": "Remote code execution in Log4j.",
            "requiredAction": "Apply updates.",
        }
    ]
}

CSV_TEXT = (
    "id,file,description,date_published,author,type,platform,date_added,date_updated,"
    "verified,codes,tags,aliases,screenshot_url,application_url,source_url\n"
    "50001,exploits/a.py,Old Exploit,2020-01-01,alice,remote,linux,2020-01-02,2020-01-03,"
    "1,CVE-2020-1111,,,,\n"
    "50003,exploits/c.py,Newest Exploit,2026-01-01,bob,local,linux,2026-01-02,2026-01-03,"
    "1,CVE-2026-2222;OSVDB-1,,,,\n"
    "50002,exploits/b.py,Middle Exploit,2023-01-01,carol,webapps,php,2023-01-02,2023-01-03,"
    "0,,, ,,,\n"
)


def kev_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=KEV_JSON)


def csv_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=CSV_TEXT)


def test_kev_parses_entries():
    client = build_client(transport=httpx.MockTransport(kev_handler))
    items, cursor = KEVConnector("kev", client, sleep=lambda _: None).fetch(None)
    assert len(items) == 1
    item = items[0]
    assert item.source_id == "CVE-2021-44228"
    assert item.extra["in_kev"] is True
    assert "Log4Shell" in item.content
    assert cursor is None


def test_exploitdb_sorted_and_limited():
    client = build_client(transport=httpx.MockTransport(csv_handler))
    connector = ExploitDBConnector("exploitdb", client, max_rows=2, sleep=lambda _: None)
    items, _ = connector.fetch(None)
    assert [i.source_id for i in items] == ["EDB-50003", "EDB-50002"]
    assert items[0].asset_type == "cve"
    assert items[0].extra["cve_id"] == "CVE-2026-2222"
    assert "https://www.exploit-db.com/exploits/50003" in items[0].content
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_connectors_cve_feeds.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.connectors.kev'`

- [ ] **Step 3: 写最小实现**

`seckb/connectors/kev.py`：

```python
from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from seckb.connectors.base import RawItem
from seckb.net import fetch_json

KEV_URL = (
    "https://www.cisa.gov/sites/default/files/feeds/"
    "known_exploited_vulnerabilities.json"
)


class KEVConnector:
    def __init__(
        self,
        name: str,
        client: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.client = client
        self.sleep = sleep

    def fetch(self, cursor: str | None) -> tuple[list[RawItem], str | None]:
        data = fetch_json(self.client, KEV_URL, sleep=self.sleep)
        items: list[RawItem] = []
        for entry in data.get("vulnerabilities", []):
            cve_id = entry.get("cveID") or ""
            if not cve_id:
                continue
            content = "\n".join(
                [
                    f"## {cve_id}（在野利用）",
                    "",
                    f"- 厂商: {entry.get('vendorProject') or '未知'}",
                    f"- 产品: {entry.get('product') or '未知'}",
                    f"- 加入 KEV 日期: {entry.get('dateAdded') or '未知'}",
                    "",
                    entry.get("shortDescription") or "",
                    "",
                    f"处置建议: {entry.get('requiredAction') or '及时升级修复'}",
                ]
            )
            items.append(
                RawItem(
                    source_id=cve_id,
                    title=f"{cve_id} KEV",
                    content=content,
                    asset_type="cve",
                    url="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
                    published_at=entry.get("dateAdded"),
                    extra={"in_kev": True, "cve_id": cve_id},
                )
            )
        return items, cursor
```

`seckb/connectors/exploitdb.py`：

```python
from __future__ import annotations

import csv
import io
import time
from collections.abc import Callable

import httpx

from seckb.connectors.base import RawItem
from seckb.net import fetch_bytes

CSV_URL = "https://gitlab.com/exploit-database/exploitdb/-/raw/main/files_exploits.csv"
PAGE_ROOT = "https://www.exploit-db.com/exploits"


class ExploitDBConnector:
    def __init__(
        self,
        name: str,
        client: httpx.Client,
        *,
        max_rows: int = 500,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.client = client
        self.max_rows = max_rows
        self.sleep = sleep

    def fetch(self, cursor: str | None) -> tuple[list[RawItem], str | None]:
        raw = fetch_bytes(self.client, CSV_URL, sleep=self.sleep)
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8", errors="replace")))
        rows = sorted(reader, key=lambda row: row.get("date_added") or "", reverse=True)
        items: list[RawItem] = []
        for row in rows[: self.max_rows]:
            edb_id = (row.get("id") or "").strip()
            if not edb_id:
                continue
            cve = (row.get("codes") or "").strip()
            page_url = f"{PAGE_ROOT}/{edb_id}"
            content = "\n".join(
                [
                    f"## EDB-{edb_id} {(row.get('description') or '').strip()}",
                    "",
                    f"- 类型: {row.get('type') or '未知'}",
                    f"- 平台: {row.get('platform') or '未知'}",
                    f"- 作者: {row.get('author') or '未知'}",
                    f"- 发布日期: {row.get('date_published') or '未知'}",
                    f"- CVE: {cve or '无'}",
                    f"- 已验证: {row.get('verified') or '0'}",
                    "",
                    f"[Exploit-DB 页面]({page_url})",
                ]
            )
            items.append(
                RawItem(
                    source_id=f"EDB-{edb_id}",
                    title=f"EDB-{edb_id} {(row.get('description') or '').strip()}",
                    content=content,
                    asset_type="cve",
                    url=page_url,
                    published_at=row.get("date_published") or None,
                    extra={"cve_id": cve or None, "poc_refs": [page_url]},
                )
            )
        return items, cursor
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_connectors_cve_feeds.py -v`
Expected: `2 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/connectors/kev.py seckb/connectors/exploitdb.py tests/test_connectors_cve_feeds.py
git commit -m "feat: KEV 与 ExploitDB 连接器"
```

---

### Task 9: Vulhub 连接器

**Files:**
- Create: `seckb/connectors/vulhub.py`
- Create: `tests/test_connector_vulhub.py`

- [ ] **Step 1: 写失败测试**

`tests/test_connector_vulhub.py`：

```python
import httpx

from seckb.connectors.vulhub import VulhubConnector
from seckb.net import build_client

TREE_JSON = {
    "tree": [
        {"path": ".github", "type": "tree"},
        {"path": ".github/workflows", "type": "tree"},
        {"path": "fastjson", "type": "tree"},
        {"path": "fastjson/1.2.24-rce", "type": "tree"},
        {"path": "fastjson/1.2.24-rce/docker-compose.yml", "type": "blob"},
        {"path": "fastjson/1.2.24-rce/README.md", "type": "blob"},
        {"path": "log4j", "type": "tree"},
        {"path": "log4j/CVE-2021-44228/docker-compose.yml", "type": "blob"},
    ]
}


def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=TREE_JSON)


def test_vulhub_environments():
    client = build_client(transport=httpx.MockTransport(handler))
    items, _ = VulhubConnector("vulhub", client, sleep=lambda _: None).fetch(None)
    ids = sorted(i.source_id for i in items)
    assert ids == ["vulhub:1.2.24-rce", "vulhub:CVE-2021-44228"]
    fastjson = next(i for i in items if i.source_id == "vulhub:1.2.24-rce")
    assert fastjson.asset_type == "writeup"
    assert "docker-compose.yml" in fastjson.content
    assert "https://github.com/vulhub/vulhub/tree/master/fastjson/1.2.24-rce" in fastjson.content
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_connector_vulhub.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.connectors.vulhub'`

- [ ] **Step 3: 写最小实现**

`seckb/connectors/vulhub.py`：

```python
from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from seckb.connectors.base import RawItem
from seckb.net import fetch_json

TREE_URL = "https://api.github.com/repos/vulhub/vulhub/git/trees/master?recursive=1"
TREE_PAGE = "https://github.com/vulhub/vulhub/tree/master"


class VulhubConnector:
    def __init__(
        self,
        name: str,
        client: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.client = client
        self.sleep = sleep

    def fetch(self, cursor: str | None) -> tuple[list[RawItem], str | None]:
        data = fetch_json(self.client, TREE_URL, sleep=self.sleep)
        nodes = data.get("tree") or []
        categories = {
            node["path"]
            for node in nodes
            if node.get("type") == "tree" and "/" not in node.get("path", "")
        }
        envs: dict[str, list[str]] = {}
        for node in nodes:
            path = node.get("path") or ""
            if "/" not in path or node.get("type") != "blob":
                continue
            category, _, rest = path.partition("/")
            if category not in categories or not rest:
                continue
            env = rest.split("/")[0]
            if "/" in rest:
                envs.setdefault(env, []).append(path)
        items: list[RawItem] = []
        for env, files in sorted(envs.items()):
            url = f"{TREE_PAGE}/{env}"
            content = "\n".join(
                [f"## Vulhub 环境 {env}", "", f"- 环境目录: {url}", "", "包含文件:", ""]
                + [f"- {path}" for path in sorted(files)]
            )
            items.append(
                RawItem(
                    source_id=f"vulhub:{env}",
                    title=f"Vulhub {env}",
                    content=content,
                    asset_type="writeup",
                    url=url,
                    extra={"site": "vulhub"},
                )
            )
        return items, cursor
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_connector_vulhub.py -v`
Expected: `1 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/connectors/vulhub.py tests/test_connector_vulhub.py
git commit -m "feat: Vulhub 连接器"
```

---

### Task 10: 采集编排（连接器注册表、游标、runs）

**Files:**
- Modify: `seckb/connectors/__init__.py`（build_connector 注册表）
- Create: `seckb/collect.py`
- Create: `tests/test_collect.py`

- [ ] **Step 1: 写失败测试**

`tests/test_collect.py`：

```python
from seckb.collect import collect_all, run_source
from seckb.connectors import build_connector
from seckb.connectors.base import RawItem


class FakeConnector:
    def __init__(self, name, items, new_cursor=None, error=None):
        self.name = name
        self.items = items
        self.new_cursor = new_cursor
        self.error = error
        self.cursors: list[str | None] = []

    def fetch(self, cursor):
        self.cursors.append(cursor)
        if self.error:
            raise RuntimeError(self.error)
        return self.items, self.new_cursor


def test_run_source_stores_cursor_and_run_log(kb):
    connector = FakeConnector(
        "fake",
        [RawItem(source_id="a1", title="条目一", content="内容一。", url=None)],
        new_cursor="2026-09-01",
    )
    report = run_source(kb.conn, kb.settings, connector)
    assert report.imported == 1
    row = kb.conn.execute("SELECT * FROM sources WHERE name = 'fake'").fetchone()
    assert row["last_cursor"] == "2026-09-01"
    assert row["health"] == "ok"
    run = kb.conn.execute("SELECT * FROM runs WHERE source = 'fake'").fetchone()
    assert run["imported"] == 1
    assert run["finished_at"] is not None


def test_run_source_failure_marks_health(kb):
    connector = FakeConnector("fake", [], error="boom")
    report = run_source(kb.conn, kb.settings, connector)
    assert report.error == "boom"
    row = kb.conn.execute("SELECT * FROM sources WHERE name = 'fake'").fetchone()
    assert row["health"] == "error"


def test_collect_all_isolates_failures(kb, monkeypatch):
    import seckb.collect as collect_mod

    good = FakeConnector("good", [RawItem(source_id="g1", title="g", content="g。")])
    bad = FakeConnector("bad", [], error="down")
    monkeypatch.setattr(
        collect_mod, "build_connectors", lambda settings: {"good": good, "bad": bad}
    )
    reports = collect_all(kb.conn, kb.settings)
    by_name = {r.source: r for r in reports}
    assert by_name["good"].imported == 1
    assert by_name["bad"].error == "down"


def test_build_connector_registry():
    from seckb.net import build_client

    client = build_client()
    connector = build_connector("rss", {"type": "rss", "feeds": ["https://e.com/f"]}, client)
    assert connector.name == "rss"
    connector2 = build_connector("nvd", {"type": "nvd", "days_back": 3}, client)
    assert connector2.name == "nvd"
    client.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_collect.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.collect'`

- [ ] **Step 3: 写最小实现**

`seckb/connectors/__init__.py` 替换为：

```python
from __future__ import annotations

import httpx

from seckb.connectors.base import Connector
from seckb.connectors.exploitdb import ExploitDBConnector
from seckb.connectors.github import GitHubConnector
from seckb.connectors.kev import KEVConnector
from seckb.connectors.nvd import NVDConnector
from seckb.connectors.rss import RSSConnector
from seckb.connectors.vulhub import VulhubConnector


def build_connector(name: str, config: dict, client: httpx.Client) -> Connector:
    kind = config.get("type")
    if kind == "rss":
        return RSSConnector(name, list(config.get("feeds") or []), client)
    if kind == "github":
        return GitHubConnector(
            name,
            client,
            queries=list(config.get("search_queries") or []),
            awesome_repos=list(config.get("awesome_repos") or []),
        )
    if kind == "nvd":
        return NVDConnector(
            name,
            client,
            days_back=int(config.get("days_back", 7)),
            max_pages=int(config.get("max_pages", 5)),
        )
    if kind == "kev":
        return KEVConnector(name, client)
    if kind == "exploitdb":
        return ExploitDBConnector(name, client, max_rows=int(config.get("max_rows", 500)))
    if kind == "vulhub":
        return VulhubConnector(name, client)
    raise ValueError(f"未知连接器类型: {kind}")
```

`seckb/collect.py`：

```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from seckb.config import Settings
from seckb.connectors import build_connector
from seckb.connectors.base import Connector
from seckb.net import build_client
from seckb.pipeline.ingest import ingest_items


@dataclass
class RunReport:
    source: str
    fetched: int = 0
    imported: int = 0
    skipped: int = 0
    updated: int = 0
    error: str | None = None
    run_id: int = 0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def get_cursor(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute("SELECT last_cursor FROM sources WHERE name = ?", (name,)).fetchone()
    return row["last_cursor"] if row else None


def set_cursor(
    conn: sqlite3.Connection, name: str, cursor: str | None, *, health: str = "ok"
) -> None:
    conn.execute(
        """
        INSERT INTO sources(name, last_cursor, last_run_at, health) VALUES(?,?,?,?)
        ON CONFLICT(name) DO UPDATE SET
          last_cursor = excluded.last_cursor,
          last_run_at = excluded.last_run_at,
          health = excluded.health
        """,
        (name, cursor, _now(), health),
    )
    conn.commit()


def _record_run_start(conn: sqlite3.Connection, source: str) -> int:
    cursor = conn.execute(
        "INSERT INTO runs(source, started_at) VALUES(?,?)", (source, _now())
    )
    conn.commit()
    return cursor.lastrowid


def _record_run_finish(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    fetched: int = 0,
    imported: int = 0,
    skipped: int = 0,
    failed: int = 0,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE runs SET finished_at = ?, fetched = ?, imported = ?, skipped = ?,
                        failed = ?, error = ?
        WHERE id = ?
        """,
        (_now(), fetched, imported, skipped, failed, error, run_id),
    )
    conn.commit()


def run_source(
    conn: sqlite3.Connection, settings: Settings, connector: Connector
) -> RunReport:
    run_id = _record_run_start(conn, connector.name)
    cursor = get_cursor(conn, connector.name)
    try:
        items, new_cursor = connector.fetch(cursor)
    except Exception as exc:
        set_cursor(conn, connector.name, cursor, health="error")
        _record_run_finish(conn, run_id, failed=1, error=str(exc))
        return RunReport(source=connector.name, error=str(exc), run_id=run_id)
    stats = ingest_items(conn, settings, items, source=connector.name)
    set_cursor(conn, connector.name, new_cursor or cursor, health="ok")
    _record_run_finish(
        conn,
        run_id,
        fetched=len(items),
        imported=stats.imported,
        skipped=stats.duplicated + stats.skipped,
    )
    return RunReport(
        source=connector.name,
        fetched=len(items),
        imported=stats.imported,
        skipped=stats.duplicated + stats.skipped,
        updated=stats.updated,
        run_id=run_id,
    )


def build_connectors(settings: Settings) -> dict[str, Connector]:
    client = build_client()
    connectors: dict[str, Connector] = {}
    for name, config in settings.sources.items():
        if not config.get("enabled", True):
            continue
        connectors[name] = build_connector(name, config, client)
    return connectors


def collect_all(
    conn: sqlite3.Connection, settings: Settings, *, only: str | None = None
) -> list[RunReport]:
    connectors = build_connectors(settings)
    reports: list[RunReport] = []
    for name, connector in connectors.items():
        if only and name != only:
            continue
        reports.append(run_source(conn, settings, connector))
    return reports
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_collect.py -v`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/connectors/__init__.py seckb/collect.py tests/test_collect.py
git commit -m "feat: 采集编排（注册表/游标/runs 日志）"
```

---

### Task 11: LLM Provider（OpenAI 兼容）

**Files:**
- Create: `seckb/enrich/__init__.py`（空）
- Create: `seckb/enrich/llm.py`
- Create: `tests/test_enrich_llm.py`

- [ ] **Step 1: 写失败测试**

`tests/test_enrich_llm.py`：

```python
import httpx
import pytest

from seckb.enrich.llm import LLMError, OpenAICompatProvider, build_provider
from seckb.net import build_client


def test_complete_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"summary": "ok"}'}}]}
        )

    client = build_client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatProvider(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="test-model",
        client=client,
        sleep=lambda _: None,
    )
    assert provider.complete("hi") == '{"summary": "ok"}'


def test_complete_retries_429():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})

    client = build_client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatProvider(
        base_url="https://api.example.com/v1",
        api_key="k",
        model="m",
        client=client,
        sleep=lambda _: None,
    )
    assert provider.complete("hi") == "done"
    assert len(calls) == 2


def test_complete_400_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    client = build_client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatProvider(
        base_url="https://api.example.com/v1",
        api_key="k",
        model="m",
        client=client,
        sleep=lambda _: None,
    )
    with pytest.raises(LLMError):
        provider.complete("hi")


def test_build_provider_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = {"provider": {"api_key_env": "DEEPSEEK_API_KEY"}}
    assert build_provider(config) is None


def test_build_provider_with_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    config = {
        "provider": {
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key_env": "DEEPSEEK_API_KEY",
        }
    }
    provider = build_provider(config)
    assert provider is not None
    assert provider.model == "deepseek-chat"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_enrich_llm.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.enrich'`

- [ ] **Step 3: 写最小实现**

`seckb/enrich/__init__.py`（空）

`seckb/enrich/llm.py`：

```python
from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Protocol

import httpx

from seckb.net import build_client

RETRY_STATUS = {429, 500, 502, 503, 504}


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    model: str

    def complete(self, prompt: str) -> str: ...


class OpenAICompatProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.Client | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1600,
        attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.client = client or build_client()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.attempts = attempts
        self.sleep = sleep

    def complete(self, prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(1, self.attempts + 1):
            response = self.client.post(url, json=payload, headers=headers)
            if response.status_code in RETRY_STATUS and attempt < self.attempts:
                self.sleep(0.5 * 2**attempt)
                continue
            if response.status_code >= 400:
                raise LLMError(f"LLM HTTP {response.status_code}: {response.text[:200]}")
            try:
                return response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError) as exc:
                raise LLMError(f"LLM 响应格式异常: {exc}") from exc
        raise LLMError("LLM 重试次数耗尽")


def build_provider(config: dict, *, client: httpx.Client | None = None) -> LLMProvider | None:
    provider_config = (config or {}).get("provider") or {}
    api_key = os.environ.get(provider_config.get("api_key_env", "DEEPSEEK_API_KEY"))
    if not api_key:
        return None
    return OpenAICompatProvider(
        base_url=provider_config.get("base_url", "https://api.deepseek.com/v1"),
        api_key=api_key,
        model=provider_config.get("model", "deepseek-chat"),
        client=client,
        temperature=float(provider_config.get("temperature", 0.2)),
        max_tokens=int(provider_config.get("max_tokens", 1600)),
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_enrich_llm.py -v`
Expected: `5 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/enrich/__init__.py seckb/enrich/llm.py tests/test_enrich_llm.py
git commit -m "feat: LLM Provider（OpenAI 兼容，默认 DeepSeek）"
```

---

### Task 12: 富化解析器与提示词

**Files:**
- Create: `seckb/enrich/parser.py`
- Create: `seckb/enrich/prompts.py`
- Create: `tests/test_enrich_parser.py`

- [ ] **Step 1: 写失败测试**

`tests/test_enrich_parser.py`：

```python
import pytest

from seckb.enrich.parser import EnrichmentParseError, parse_enrichment
from seckb.enrich.prompts import build_prompt

GOOD = """
{
  "summary": "介绍 fastjson 反序列化漏洞的利用方式。",
  "key_takeaways": ["影响 1.2.24 以下版本", "需要 autotype 开启"],
  "tags": ["反序列化", "fastjson"],
  "entities": {"cve": ["CVE-2017-18349"], "tool": ["marshalsec"], "attack": ["T1059"]},
  "snippets": [
    {"kind": "command", "lang": "bash", "tool": "java", "content": "java -jar marshalsec.jar", "context": "启动 LDAP 服务"}
  ]
}
"""


def test_parse_plain_json():
    result = parse_enrichment(GOOD)
    assert "fastjson" in result.summary
    assert result.key_takeaways[0].startswith("影响")
    assert result.tags == ["反序列化", "fastjson"]
    assert result.entities["cve"] == ["CVE-2017-18349"]
    assert result.snippets[0]["kind"] == "command"
    assert result.snippets[0]["tool"] == "java"


def test_parse_fenced_json():
    fenced = "```json\n" + GOOD + "\n```"
    assert parse_enrichment(fenced).summary == parse_enrichment(GOOD).summary


def test_parse_missing_summary_raises():
    with pytest.raises(EnrichmentParseError):
        parse_enrichment('{"key_takeaways": []}')


def test_parse_invalid_raises():
    with pytest.raises(EnrichmentParseError):
        parse_enrichment("这不是 JSON")


def test_snippets_without_content_are_dropped():
    raw = '{"summary": "s", "snippets": [{"kind": "code"}, {"content": "ls -la"}]}'
    result = parse_enrichment(raw)
    assert len(result.snippets) == 1
    assert result.snippets[0]["kind"] == "code"


def test_build_prompt_clips_text():
    prompt = build_prompt("标题", "x" * 50000)
    assert "标题" in prompt
    assert len(prompt) < 20000
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_enrich_parser.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.enrich.parser'`

- [ ] **Step 3: 写最小实现**

`seckb/enrich/parser.py`：

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field

ENTITY_KINDS = ("cve", "tool", "attack", "owasp", "product")


class EnrichmentParseError(Exception):
    pass


@dataclass
class Enrichment:
    summary: str
    key_takeaways: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    snippets: list[dict] = field(default_factory=list)


def _str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def parse_enrichment(raw: str) -> Enrichment:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise EnrichmentParseError("响应中没有 JSON 对象")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise EnrichmentParseError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise EnrichmentParseError("JSON 顶层不是对象")
    summary = str(data.get("summary") or "").strip()
    if not summary:
        raise EnrichmentParseError("缺少 summary")
    entities_raw = data.get("entities") or {}
    entities = {
        kind: _str_list(entities_raw.get(kind)) for kind in ENTITY_KINDS
    }
    snippets: list[dict] = []
    for entry in data.get("snippets") or []:
        if not isinstance(entry, dict):
            continue
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        snippets.append(
            {
                "kind": str(entry.get("kind") or "code"),
                "lang": entry.get("lang"),
                "tool": entry.get("tool"),
                "content": content,
                "context": str(entry.get("context") or ""),
            }
        )
    return Enrichment(
        summary=summary,
        key_takeaways=_str_list(data.get("key_takeaways")),
        tags=_str_list(data.get("tags")),
        entities=entities,
        snippets=snippets,
    )
```

`seckb/enrich/prompts.py`：

```python
from __future__ import annotations

PROMPT_TEMPLATE = """你是网络安全知识库的编目助手。阅读下面的资料，输出一个 JSON 对象（不要输出任何其它文字）：
{{"summary": "一到两句话的摘要", "key_takeaways": ["要点1", "要点2"], "tags": ["标签1", "标签2"], "entities": {{"cve": [], "tool": [], "attack": [], "owasp": [], "product": []}}, "snippets": [{{"kind": "command|payload|oneliner|code", "lang": "bash", "tool": "nmap", "content": "可执行的命令或载荷原文", "context": "用途说明"}}]}}

要求：
- tags 用中文或英文短词，3~8 个
- entities 只填资料中真实出现的 CVE 编号、工具名、ATT&CK 技术号、OWASP 分类、产品名
- snippets 只提取资料中的命令、载荷、代码，不要杜撰
- summary 必须基于资料内容

标题：{title}

正文：
{text}
"""


def build_prompt(title: str, text: str, *, max_chars: int = 12000) -> str:
    clipped = text[:max_chars]
    return PROMPT_TEMPLATE.format(title=title, text=clipped)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_enrich_parser.py -v`
Expected: `6 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/enrich/parser.py seckb/enrich/prompts.py tests/test_enrich_parser.py
git commit -m "feat: 富化解析器与提示词"
```

---

### Task 13: 富化队列（知识卡片 / 标签 / 实体 / 片段）

**Files:**
- Create: `seckb/enrich/queue.py`
- Create: `tests/test_enrich_queue.py`

- [ ] **Step 1: 写失败测试**

`tests/test_enrich_queue.py`：

```python
import json
from pathlib import Path

from seckb.enrich.queue import enqueue, process_jobs
from seckb.pipeline.importer import import_file
from seckb.utils.tokens import estimate_tokens

GOOD_JSON = json.dumps(
    {
        "summary": "fastjson 反序列化利用总结。",
        "key_takeaways": ["需要 autotype 开启"],
        "tags": ["反序列化", "fastjson"],
        "entities": {"cve": ["CVE-2017-18349"], "tool": ["marshalsec"]},
        "snippets": [
            {
                "kind": "command",
                "lang": "bash",
                "tool": "java",
                "content": "java -jar marshalsec.jar",
                "context": "启动 LDAP",
            }
        ],
    }
)


class FakeLLM:
    model = "fake-model"

    def __init__(self, response=GOOD_JSON, error=None):
        self.response = response
        self.error = error
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self.error:
            raise RuntimeError(self.error)
        return self.response


def make_asset(kb, tmp_path: Path) -> int:
    src = tmp_path / "post.md"
    src.write_text(
        "# fastjson 反序列化\n\nCVE-2017-18349 利用记录，使用 marshalsec 启动 LDAP。\n\n"
        "```bash\njava -jar marshalsec.jar\n```\n",
        encoding="utf-8",
    )
    return import_file(kb.conn, kb.settings, src).asset_id


def test_process_jobs_creates_card_and_entities(kb, tmp_path: Path):
    asset_id = make_asset(kb, tmp_path)
    enqueue(kb.conn, asset_id)
    report = process_jobs(kb.conn, kb.settings, FakeLLM())
    assert report.succeeded == 1
    card = kb.conn.execute("SELECT * FROM cards WHERE asset_id = ?", (asset_id,)).fetchone()
    assert card["model"] == "fake-model"
    assert "fastjson" in card["summary"]
    tags = json.loads(
        kb.conn.execute("SELECT tags FROM assets WHERE id = ?", (asset_id,)).fetchone()["tags"]
    )
    assert "反序列化" in tags
    entities = kb.conn.execute(
        """SELECT e.kind, e.name FROM asset_entities ae JOIN entities e ON e.id = ae.entity_id
           WHERE ae.asset_id = ?""",
        (asset_id,),
    ).fetchall()
    pairs = {(row["kind"], row["name"]) for row in entities}
    assert ("cve", "CVE-2017-18349") in pairs
    assert ("tool", "marshalsec") in pairs
    llm_snippet = kb.conn.execute(
        "SELECT * FROM snippets WHERE asset_id = ? AND content = 'java -jar marshalsec.jar'",
        (asset_id,),
    ).fetchone()
    assert llm_snippet is not None
    job = kb.conn.execute("SELECT * FROM jobs WHERE asset_id = ?", (asset_id,)).fetchone()
    assert job["status"] == "done"


def test_process_jobs_respects_input_budget(kb, tmp_path: Path):
    asset_id = make_asset(kb, tmp_path)
    enqueue(kb.conn, asset_id)
    kb.settings.enrich = {"queue": {"max_input_tokens": 10}}
    provider = FakeLLM()
    process_jobs(kb.conn, kb.settings, provider)
    prompt = provider.calls[0]
    body = prompt.split("正文：", 1)[1]
    assert estimate_tokens(body) <= 40


def test_process_jobs_retries_then_fails(kb, tmp_path: Path):
    asset_id = make_asset(kb, tmp_path)
    enqueue(kb.conn, asset_id)
    kb.settings.enrich = {"queue": {"max_attempts": 1}}
    report = process_jobs(kb.conn, kb.settings, FakeLLM(error="llm down"))
    assert report.failed == 1
    job = kb.conn.execute("SELECT * FROM jobs WHERE asset_id = ?", (asset_id,)).fetchone()
    assert job["status"] == "failed"
    assert job["attempts"] == 1
    assert "llm down" in job["last_error"]


def test_process_jobs_skips_done_jobs(kb, tmp_path: Path):
    asset_id = make_asset(kb, tmp_path)
    enqueue(kb.conn, asset_id)
    process_jobs(kb.conn, kb.settings, FakeLLM())
    report = process_jobs(kb.conn, kb.settings, FakeLLM())
    assert report.processed == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_enrich_queue.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.enrich.queue'`

- [ ] **Step 3: 写最小实现**

`seckb/enrich/queue.py`：

```python
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from seckb.config import Settings
from seckb.enrich.llm import LLMProvider
from seckb.enrich.parser import Enrichment, parse_enrichment
from seckb.enrich.prompts import build_prompt
from seckb.pipeline.entities import link_entity
from seckb.utils.tokens import estimate_tokens


@dataclass
class QueueReport:
    processed: int = 0
    succeeded: int = 0
    failed: int = 0


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def enqueue(conn: sqlite3.Connection, asset_id: int, kind: str = "summary") -> int:
    cursor = conn.execute(
        "INSERT INTO jobs(asset_id, kind, status, created_at) VALUES(?,?, 'pending', ?)",
        (asset_id, kind, _now()),
    )
    conn.commit()
    return cursor.lastrowid


def pending_jobs(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM jobs WHERE status = 'pending' ORDER BY id LIMIT ?", (limit,)
    ).fetchall()


def _asset_text(conn: sqlite3.Connection, asset_id: int, max_input_tokens: int) -> str:
    chunks = conn.execute(
        "SELECT content_md FROM chunks WHERE asset_id = ? ORDER BY seq", (asset_id,)
    ).fetchall()
    parts: list[str] = []
    total = 0
    for chunk in chunks:
        tokens = estimate_tokens(chunk["content_md"])
        if parts and total + tokens > max_input_tokens:
            break
        parts.append(chunk["content_md"])
        total += tokens
    return "\n\n".join(parts)


def save_card(
    conn: sqlite3.Connection,
    asset_id: int,
    enrichment: Enrichment,
    *,
    model: str | None,
) -> None:
    card_json = json.dumps(
        {
            "summary": enrichment.summary,
            "key_takeaways": enrichment.key_takeaways,
            "tags": enrichment.tags,
            "entities": enrichment.entities,
        },
        ensure_ascii=False,
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO cards(asset_id, summary, key_takeaways, card_json, model, generated_at)
        VALUES(?,?,?,?,?,?)
        """,
        (
            asset_id,
            enrichment.summary,
            json.dumps(enrichment.key_takeaways, ensure_ascii=False),
            card_json,
            model,
            _now(),
        ),
    )


def _merge_tags(conn: sqlite3.Connection, asset_id: int, new_tags: list[str]) -> None:
    row = conn.execute("SELECT tags FROM assets WHERE id = ?", (asset_id,)).fetchone()
    existing = json.loads(row["tags"] or "[]") if row else []
    merged = list(dict.fromkeys([*existing, *new_tags]))
    conn.execute(
        "UPDATE assets SET tags = ? WHERE id = ?",
        (json.dumps(merged, ensure_ascii=False), asset_id),
    )


def _save_entities(conn: sqlite3.Connection, asset_id: int, enrichment: Enrichment) -> None:
    for kind, names in enrichment.entities.items():
        for name in names:
            link_entity(conn, asset_id, kind, name)


def _save_snippets(conn: sqlite3.Connection, asset_id: int, enrichment: Enrichment) -> None:
    for snippet in enrichment.snippets:
        exists = conn.execute(
            "SELECT id FROM snippets WHERE asset_id = ? AND content = ?",
            (asset_id, snippet["content"]),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO snippets(asset_id, kind, lang, tool, content, context) VALUES(?,?,?,?,?,?)",
            (
                asset_id,
                snippet["kind"],
                snippet["lang"],
                snippet["tool"],
                snippet["content"],
                snippet["context"],
            ),
        )


def _mark_job(
    conn: sqlite3.Connection, job_id: int, *, status: str, error: str | None = None
) -> None:
    conn.execute(
        """
        UPDATE jobs SET status = ?, attempts = attempts + 1, last_error = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, error, _now(), job_id),
    )
    conn.commit()


def process_jobs(
    conn: sqlite3.Connection,
    settings: Settings,
    provider: LLMProvider,
    *,
    limit: int = 10,
) -> QueueReport:
    queue_config = (settings.enrich or {}).get("queue") or {}
    max_input_tokens = int(queue_config.get("max_input_tokens", 6000))
    max_attempts = int(queue_config.get("max_attempts", 3))
    report = QueueReport()
    for job in pending_jobs(conn, limit):
        report.processed += 1
        asset = conn.execute(
            "SELECT * FROM assets WHERE id = ?", (job["asset_id"],)
        ).fetchone()
        if asset is None:
            _mark_job(conn, job["id"], status="failed", error="资产不存在")
            report.failed += 1
            continue
        text = _asset_text(conn, job["asset_id"], max_input_tokens)
        prompt = build_prompt(asset["title"], text)
        try:
            raw = provider.complete(prompt)
            enrichment = parse_enrichment(raw)
        except Exception as exc:
            attempts = job["attempts"] + 1
            status = "failed" if attempts >= max_attempts else "pending"
            _mark_job(conn, job["id"], status=status, error=str(exc))
            report.failed += 1
            continue
        save_card(conn, job["asset_id"], enrichment, model=getattr(provider, "model", None))
        _merge_tags(conn, job["asset_id"], enrichment.tags)
        _save_entities(conn, job["asset_id"], enrichment)
        _save_snippets(conn, job["asset_id"], enrichment)
        _mark_job(conn, job["id"], status="done")
        report.succeeded += 1
    return report
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_enrich_queue.py -v`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/enrich/queue.py tests/test_enrich_queue.py
git commit -m "feat: 富化队列（卡片/标签/实体/片段/重试）"
```

---

### Task 14: 调度守护进程

**Files:**
- Create: `seckb/daemon.py`
- Create: `tests/test_daemon.py`

- [ ] **Step 1: 写失败测试**

`tests/test_daemon.py`：

```python
from pathlib import Path

from seckb.config import Settings
from seckb.daemon import build_scheduler, parse_cron


def test_parse_cron():
    assert parse_cron("0 */6 * * *") == {
        "minute": "0",
        "hour": "*/6",
        "day": "*",
        "month": "*",
        "day_of_week": "*",
    }


def test_build_scheduler_registers_jobs():
    settings = Settings(
        kb_root=Path("D:/KB"),
        schedule={
            "collect": {"rss": "0 */6 * * *", "nvd": "0 3 * * *"},
            "enrich": {"every_minutes": 10},
        },
    )
    scheduler = build_scheduler(settings)
    ids = sorted(job.id for job in scheduler.get_jobs())
    assert ids == ["collect:nvd", "collect:rss", "enrich"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_daemon.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.daemon'`

- [ ] **Step 3: 写最小实现**

`seckb/daemon.py`：

```python
from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler

from seckb.collect import collect_all
from seckb.config import Settings, load_settings
from seckb.db.connection import init_db
from seckb.enrich.llm import build_provider
from seckb.enrich.queue import process_jobs


def parse_cron(expr: str) -> dict:
    minute, hour, day, month, day_of_week = expr.split()
    return {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": day_of_week,
    }


def _collect_job(source: str) -> None:
    settings = load_settings()
    conn = init_db(settings.kb_root)
    try:
        collect_all(conn, settings, only=source)
    finally:
        conn.close()


def _enrich_job() -> None:
    settings = load_settings()
    provider = build_provider(settings.enrich)
    if provider is None:
        return
    conn = init_db(settings.kb_root)
    try:
        limit = int((settings.enrich.get("queue") or {}).get("max_assets_per_run", 10))
        process_jobs(conn, settings, provider, limit=limit)
    finally:
        conn.close()


def build_scheduler(settings: Settings) -> BlockingScheduler:
    scheduler = BlockingScheduler()
    for name, expr in (settings.schedule.get("collect") or {}).items():
        scheduler.add_job(
            _collect_job,
            "cron",
            id=f"collect:{name}",
            kwargs={"source": name},
            **parse_cron(expr),
        )
    every_minutes = (settings.schedule.get("enrich") or {}).get("every_minutes")
    if every_minutes:
        scheduler.add_job(
            _enrich_job,
            "interval",
            id="enrich",
            minutes=int(every_minutes),
        )
    return scheduler
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_daemon.py -v`
Expected: `2 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/daemon.py tests/test_daemon.py
git commit -m "feat: APScheduler 调度守护"
```

---

### Task 15: 向量索引（Ollama bge-m3 + LanceDB）

**Files:**
- Create: `seckb/indexer/vectors.py`
- Create: `tests/test_vectors.py`

- [ ] **Step 1: 写失败测试**

`tests/test_vectors.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vectors.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.indexer.vectors'`

- [ ] **Step 3: 写最小实现**

`seckb/indexer/vectors.py`：

```python
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
    except Exception:
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vectors.py -v`
Expected: `5 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/indexer/vectors.py tests/test_vectors.py
git commit -m "feat: 向量索引（Ollama bge-m3 + LanceDB）"
```

---

### Task 16: Meilisearch 索引

**Files:**
- Create: `seckb/indexer/meili.py`
- Create: `tests/test_meili.py`

- [ ] **Step 1: 写失败测试**

`tests/test_meili.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_meili.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.indexer.meili'`

- [ ] **Step 3: 写最小实现**

`seckb/indexer/meili.py`：

```python
from __future__ import annotations

import json
import os
import sqlite3

import httpx

from seckb.net import build_client

INDEX = "assets"
CONTENT_CHAR_LIMIT = 4000


class MeiliError(Exception):
    pass


class MeiliClient:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:7700",
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or build_client()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def ensure_index(self, index: str = INDEX) -> None:
        response = self.client.post(
            f"{self.base_url}/indexes",
            json={"uid": index, "primaryKey": "id"},
            headers=self._headers(),
        )
        if response.status_code not in (200, 201, 409):
            raise MeiliError(f"创建索引失败: HTTP {response.status_code}")
        response = self.client.patch(
            f"{self.base_url}/indexes/{index}/settings",
            json={
                "searchableAttributes": ["title", "summary", "tags", "content"],
                "filterableAttributes": ["type", "tags", "source", "lang"],
            },
            headers=self._headers(),
        )
        if response.status_code >= 400:
            raise MeiliError(f"更新索引设置失败: HTTP {response.status_code}")

    def upsert(self, docs: list[dict], index: str = INDEX) -> None:
        response = self.client.post(
            f"{self.base_url}/indexes/{index}/documents",
            json=docs,
            headers=self._headers(),
        )
        if response.status_code not in (200, 202):
            raise MeiliError(f"写入文档失败: HTTP {response.status_code}")

    def search(
        self, query: str, *, limit: int = 10, filters: str | None = None, index: str = INDEX
    ) -> list[dict]:
        payload: dict = {"q": query, "limit": limit}
        if filters:
            payload["filter"] = filters
        response = self.client.post(
            f"{self.base_url}/indexes/{index}/search",
            json=payload,
            headers=self._headers(),
        )
        if response.status_code >= 400:
            raise MeiliError(f"检索失败: HTTP {response.status_code}")
        return response.json().get("hits", [])


def build_doc(conn: sqlite3.Connection, asset_id: int) -> dict:
    asset = conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
    if asset is None:
        raise MeiliError(f"资产不存在: {asset_id}")
    card = conn.execute("SELECT summary FROM cards WHERE asset_id = ?", (asset_id,)).fetchone()
    chunks = conn.execute(
        "SELECT content_md FROM chunks WHERE asset_id = ? ORDER BY seq", (asset_id,)
    ).fetchall()
    content = "\n\n".join(chunk["content_md"] for chunk in chunks)[:CONTENT_CHAR_LIMIT]
    return {
        "id": asset_id,
        "type": asset["type"],
        "title": asset["title"],
        "lang": asset["lang"],
        "source": asset["source"],
        "source_url": asset["source_url"],
        "category": asset["category"],
        "published_at": asset["published_at"],
        "tags": json.loads(asset["tags"] or "[]"),
        "summary": card["summary"] if card else "",
        "content": content,
    }


def index_asset(conn: sqlite3.Connection, client, asset_id: int) -> None:
    client.upsert([build_doc(conn, asset_id)])


def rebuild(conn: sqlite3.Connection, client, *, batch_size: int = 100) -> int:
    ids = [row["id"] for row in conn.execute("SELECT id FROM assets ORDER BY id")]
    total = 0
    batch: list[dict] = []
    for asset_id in ids:
        batch.append(build_doc(conn, asset_id))
        if len(batch) >= batch_size:
            client.upsert(batch)
            total += len(batch)
            batch = []
    if batch:
        client.upsert(batch)
        total += len(batch)
    return total


def build_meili_client(config: dict, *, client: httpx.Client | None = None) -> MeiliClient:
    meili = (config or {}).get("meili") or {}
    api_key = os.environ.get(meili.get("api_key_env", "MEILI_MASTER_KEY"))
    return MeiliClient(
        base_url=meili.get("base_url", "http://127.0.0.1:7700"),
        api_key=api_key,
        client=client,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_meili.py -v`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/indexer/meili.py tests/test_meili.py
git commit -m "feat: Meilisearch 索引（文档构建/批量重建）"
```

---

### Task 17: CLI 扩展、端到端验收与收尾

**Files:**
- Modify: `seckb/cli.py`（追加命令）
- Create: `tests/test_cli_v2.py`
- Create: `tests/test_e2e_v2.py`

- [ ] **Step 1: 写失败测试**

`tests/test_cli_v2.py`：

```python
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


def test_help_lists_new_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("collect", "enrich", "embed", "index", "sources", "daemon"):
        assert command in result.output


def test_enrich_without_api_key_exits_1(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg = write_config(tmp_path)
    result = runner.invoke(app, ["--config", str(cfg), "enrich"])
    assert result.exit_code == 1
    assert "API Key" in result.output


def test_sources_command_lists_configured_sources(tmp_path: Path):
    cfg = write_config(tmp_path)
    (cfg / "sources.yaml").write_text(
        "sources:\n  rss:\n    type: rss\n    feeds: [https://e.com/f]\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["--config", str(cfg), "sources"])
    assert result.exit_code == 0
    assert "rss" in result.output
```

`tests/test_e2e_v2.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cli_v2.py tests/test_e2e_v2.py -v`
Expected: FAIL（`enrich` 等命令不存在 / `assert ... in result.output`）

- [ ] **Step 3: 写最小实现**

`seckb/cli.py`：在 import 区把

```python
from seckb.search import search as search_kb
```

替换为：

```python
from seckb.search import search as search_kb
from seckb.collect import collect_all
from seckb.enrich.llm import build_provider
from seckb.enrich.queue import process_jobs
from seckb.indexer.meili import build_meili_client, rebuild as rebuild_meili
from seckb.indexer.vectors import build_embedder, index_asset as index_vectors
from seckb.daemon import build_scheduler
```

在 `stats` 命令之后追加：

```python
@app.command()
def collect(ctx: typer.Context, source: str = typer.Option(None, "--source")) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    reports = collect_all(conn, settings, only=source)
    for report in reports:
        console.print(
            f"{report.source}: fetched={report.fetched} imported={report.imported} "
            f"skipped={report.skipped} updated={report.updated} error={report.error or '-'}"
        )
    conn.close()


@app.command()
def enrich(ctx: typer.Context, limit: int = typer.Option(10, "--limit", "-n")) -> None:
    settings: Settings = ctx.obj
    provider = build_provider(settings.enrich)
    if provider is None:
        console.print("[red]未配置 LLM API Key（环境变量 DEEPSEEK_API_KEY），无法富化[/red]")
        raise typer.Exit(code=1)
    conn = _open(settings)
    report = process_jobs(conn, settings, provider, limit=limit)
    console.print(
        f"富化完成：处理 {report.processed}，成功 {report.succeeded}，失败 {report.failed}"
    )
    conn.close()


@app.command()
def embed(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    embedder = build_embedder(settings.enrich)
    total = 0
    for row in conn.execute("SELECT id FROM assets ORDER BY id"):
        total += index_vectors(conn, settings, embedder, row["id"])
    console.print(f"向量化完成：{total} 个切片")
    conn.close()


@app.command()
def index(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    client = build_meili_client(settings.enrich)
    client.ensure_index()
    count = rebuild_meili(conn, client)
    console.print(f"Meilisearch 重建完成：{count} 个文档")
    conn.close()


@app.command()
def sources(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    table = Table(title="采集源")
    table.add_column("名称")
    table.add_column("类型")
    table.add_column("健康")
    table.add_column("上次运行")
    table.add_column("游标", max_width=40)
    health = {
        row["name"]: row
        for row in conn.execute("SELECT * FROM sources")
    }
    for name, config in settings.sources.items():
        row = health.get(name)
        table.add_row(
            name,
            str(config.get("type")),
            row["health"] if row else "-",
            row["last_run_at"] if row else "-",
            (row["last_cursor"] or "-") if row else "-",
        )
    console.print(table)
    conn.close()


@app.command()
def daemon(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj
    scheduler = build_scheduler(settings)
    console.print("守护进程启动，任务：" + ", ".join(job.id for job in scheduler.get_jobs()))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        console.print("守护进程已停止")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cli_v2.py tests/test_e2e_v2.py -v`
Expected: `4 passed`；再跑全量 `pytest -q` 确认无回归

- [ ] **Step 5: 运行 ruff 并修复**

Run: `.venv\Scripts\python.exe -m ruff check seckb tests`
Expected: 无错误；若有则逐条最小修复后重跑全量测试。

- [ ] **Step 6: 提交**

```powershell
git add seckb/cli.py tests/test_cli_v2.py tests/test_e2e_v2.py
git commit -m "feat: CLI 采集/富化/索引命令；P1b 采集与富化完成"
```

---

## 运行前置（手工步骤，不属于任务）

1. **Ollama + bge-m3**（本机已装 Ollama）：
   ```powershell
   ollama pull bge-m3
   ```
2. **Meilisearch**（单文件二进制，下载后放到 `D:\SecurityKB\meta\bin\`）：
   ```powershell
   $rel = Invoke-RestMethod https://api.github.com/repos/meilisearch/meilisearch/releases/latest
   $url = ($rel.assets | Where-Object name -like "*windows-amd64.exe" | Select-Object -First 1).browser_download_url
   New-Item -ItemType Directory -Force D:\SecurityKB\meta\bin | Out-Null
   Invoke-WebRequest $url -OutFile D:\SecurityKB\meta\bin\meilisearch.exe
   D:\SecurityKB\meta\bin\meilisearch.exe --db-path D:\SecurityKB\meta\meili --master-key change-me
   ```
   然后在环境变量配置 `MEILI_MASTER_KEY=change-me`。
3. **LLM Key**：配置环境变量 `DEEPSEEK_API_KEY`（或在 `config/enrich.yaml` 改 `api_key_env` 指向其它 OpenAI 兼容服务）。
4. **首次全量**：
   ```powershell
   .venv\Scripts\python.exe -m seckb collect
   .venv\Scripts\python.exe -m seckb enrich
   .venv\Scripts\python.exe -m seckb embed
   .venv\Scripts\python.exe -m seckb index
   .venv\Scripts\python.exe -m seckb daemon
   ```

## 本计划明确的取舍（YAGNI）

- 不实现 HN/Reddit/CTFtime 连接器（留到后续增量计划；接口已统一，新增即一个文件+一行 YAML）
- ExploitDB 首次只拉最近 `max_rows=500` 条，全量回填留到后续
- 先知/看雪等需登录的 T2 连接器仍不在本计划（P1c 之后）
- LLM 富化只做单遍摘要+抽取，不做多轮反思或质量评分
- Meilisearch 只做整库重建（增量 upsert 由 `index_asset` 提供，批量调度优化留到后续）



