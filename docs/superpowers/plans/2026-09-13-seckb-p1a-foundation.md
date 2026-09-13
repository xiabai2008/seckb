# seckb P1a：地基与数据管线 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 seckb 项目骨架与数据管线：投递文件 → 归一化 Markdown → 切块/片段/实体 → 去重 → 归档编目 → FTS5 检索，全程可测试。

**Architecture:** Python 单包应用，SQLite 为事实源，文件按人类可读目录归档。所有能力通过 `seckb` CLI 调用；本计划不实现采集器、LLM 富化、向量检索、MCP/HTTP（分别属于 Plan P1b / P1c）。

**Tech Stack:** Python 3.12、Typer、PyYAML、SQLite（stdlib，FTS5 trigram）、BeautifulSoup4、readability-lxml、markdownify、PyMuPDF4LLM、EbookLib、pytest、ruff

**环境约定：** 所有命令在仓库根 `D:\HZR_PROJECTS\seckb` 执行，使用 `.venv\Scripts\python.exe` 直接调用虚拟环境。

---

## 文件结构（本计划结束时）

```
seckb/
├── pyproject.toml
├── .gitignore
├── config/
│   ├── settings.yaml            # kb_root
│   └── taxonomy.yaml            # 方向词典 + 工具词典
├── seckb/
│   ├── __init__.py              # __version__
│   ├── __main__.py              # python -m seckb
│   ├── cli.py                   # Typer 入口：init/import/scan/search/stats
│   ├── config.py                # Settings、load_settings
│   ├── models.py                # Asset、ChunkDraft、SnippetDraft
│   ├── search.py                # 检索门面（P1c 替换为混合检索）
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── tokens.py            # estimate_tokens
│   │   ├── hashing.py           # sha256、normalize_url、slugify
│   │   └── simhash.py           # simhash64、hamming、signed64 转换
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py        # open_db / init_db
│   │   ├── migrate.py           # 基于 PRAGMA user_version 的迁移器
│   │   └── migrations/
│   │       └── 0001_initial.sql
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── normalize.py         # HTML/PDF/EPUB/MD → Markdown
│   │   ├── chunker.py           # 标题感知切块
│   │   ├── rules.py             # CVE/ATT&CK/工具/代码片段规则抽取
│   │   ├── dedupe.py            # sha256 精确去重 + SimHash 近似去重
│   │   └── importer.py          # inbox 导入编排
│   └── indexer/
│       ├── __init__.py
│       └── fts.py               # FTS5 索引/查询
└── tests/
    ├── conftest.py              # kb fixture
    └── test_*.py
```

核心接口约定（后续计划依赖）：

- `Settings`：`kb_root: Path`、`taxonomy: dict`（键 `directions`、`tools`）
- 连接器/管线统一由 `import_file(conn, settings, src, asset_type=None) -> ImportReport` 入库
- 检索统一走 `seckb.search.search(conn, query, asset_type=None, limit=10) -> list[SearchHit]`
- `SearchHit`：`asset_id, chunk_id, title, heading_path, snippet, score`

---

### Task 1: 项目骨架与开发环境

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `seckb/__init__.py`
- Create: `seckb/__main__.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: 写失败测试**

`tests/test_smoke.py`：

```python
import seckb


def test_version():
    assert seckb.__version__ == "0.1.0"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_smoke.py -v`（若 .venv 未建，先做 Step 3 的安装再回来跑；此时应报 `No module named 'seckb'` 或找不到 seckb 包）

- [ ] **Step 3: 写最小实现**

`pyproject.toml`：

```toml
[project]
name = "seckb"
version = "0.1.0"
description = "面向 AI agent 的本地网络安全知识库"
requires-python = ">=3.12"
dependencies = [
    "typer>=0.12",
    "pyyaml>=6.0",
    "beautifulsoup4>=4.12",
    "readability-lxml>=0.8.1",
    "markdownify>=0.13",
    "pymupdf4llm>=0.0.17",
    "ebooklib>=0.18",
    "rich>=13.7",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.6"]

[project.scripts]
seckb = "seckb.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["seckb*"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

`.gitignore`：

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
*.egg-info/
build/
dist/
config/settings.local.yaml
```

`seckb/__init__.py`：

```python
__version__ = "0.1.0"
```

`seckb/__main__.py`：

```python
from seckb.cli import main

if __name__ == "__main__":
    main()
```

（本步骤 `seckb/cli.py` 尚不存在，`__main__.py` 暂时无法运行，属预期；Task 14 补全 cli。）

创建环境并安装：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_smoke.py -v`
Expected: `1 passed`

- [ ] **Step 5: 提交**

```powershell
git add pyproject.toml .gitignore seckb/__init__.py seckb/__main__.py tests/test_smoke.py
git commit -m "chore: 项目骨架与开发环境"
```

---

### Task 2: 配置加载

**Files:**
- Create: `seckb/config.py`
- Create: `config/settings.yaml`
- Create: `config/taxonomy.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

`tests/test_config.py`：

```python
from pathlib import Path

from seckb.config import Settings, load_settings


def test_load_settings_reads_yaml(tmp_path: Path):
    (tmp_path / "settings.yaml").write_text("kb_root: D:/KB-Test\n", encoding="utf-8")
    (tmp_path / "taxonomy.yaml").write_text(
        "directions:\n  web-security: [xss, sql注入]\ntools: [sqlmap, nmap]\n",
        encoding="utf-8",
    )
    settings = load_settings(tmp_path)
    assert settings.kb_root == Path("D:/KB-Test")
    assert "web-security" in settings.taxonomy["directions"]
    assert settings.taxonomy["tools"] == ["sqlmap", "nmap"]


def test_settings_db_path():
    settings = Settings(kb_root=Path("D:/KB"))
    assert settings.db_path == Path("D:/KB/meta/catalog.db")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.config'`

- [ ] **Step 3: 写最小实现**

`seckb/config.py`：

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

    @property
    def db_path(self) -> Path:
        return self.kb_root / "meta" / "catalog.db"


def load_settings(config_dir: Path | None = None) -> Settings:
    env_dir = os.environ.get("SECKB_CONFIG")
    cfg_dir = Path(env_dir) if env_dir else Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    kb_root = Path(os.environ.get("SECKB_ROOT", DEFAULT_KB_ROOT))

    settings_file = cfg_dir / "settings.yaml"
    if settings_file.exists():
        data = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
        if data.get("kb_root"):
            kb_root = Path(data["kb_root"])

    taxonomy: dict = {}
    taxonomy_file = cfg_dir / "taxonomy.yaml"
    if taxonomy_file.exists():
        taxonomy = yaml.safe_load(taxonomy_file.read_text(encoding="utf-8")) or {}

    return Settings(kb_root=kb_root, config_dir=cfg_dir, taxonomy=taxonomy)
```

`config/settings.yaml`：

```yaml
kb_root: D:/SecurityKB
```

`config/taxonomy.yaml`：

```yaml
directions:
  web-security: [web安全, xss, sql注入, ssrf, 反序列化, java安全]
  pentest: [渗透, 提权, 内网, 横向, 域渗透]
  reverse-engineering: [逆向, 脱壳, 反汇编, ida, ollvm]
  crypto: [密码学, 加密算法, rsa, aes, 对称加密]
  code-audit: [代码审计, 白盒, 审计]
  cloud-security: [云安全, 容器, kubernetes, docker, 云原生]
  ics-security: [工控, modbus, plc, scada]
  mobile-security: [安卓, android, ios, 移动安全, app逆向]
  incident-response: [应急响应, 取证, 日志分析, 溯源]
  data-security: [数据安全, 脱敏, 隐私]
tools: [nmap, sqlmap, nuclei, burp, wireshark, metasploit, mimikatz, fscan, httpx, gobuster, hashcat, john, bloodhound, impacket, responder, proxychains]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: `2 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/config.py config/ tests/test_config.py
git commit -m "feat: 配置加载（settings/taxonomy）"
```

---

### Task 3: token 估算工具

**Files:**
- Create: `seckb/utils/__init__.py`（空文件）
- Create: `seckb/utils/tokens.py`
- Test: `tests/test_tokens.py`

- [ ] **Step 1: 写失败测试**

`tests/test_tokens.py`：

```python
from seckb.utils.tokens import estimate_tokens


def test_empty():
    assert estimate_tokens("") == 0


def test_english_words():
    assert estimate_tokens("hello world") == 2


def test_cjk_chars_count_individually():
    assert estimate_tokens("你好世界") == 4


def test_mixed_text_is_reasonable():
    text = "使用 sqlmap 进行 SQL 注入测试"
    assert 8 <= estimate_tokens(text) <= 16
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tokens.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.utils'`

- [ ] **Step 3: 写最小实现**

`seckb/utils/__init__.py`（空）

`seckb/utils/tokens.py`：

```python
from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_NON_TEXT_RE = re.compile(r"[^\w\s\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    words = len(_WORD_RE.findall(text))
    punctuation = len(_NON_TEXT_RE.findall(text))
    return cjk + words + punctuation // 4
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tokens.py -v`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/utils/ tests/test_tokens.py
git commit -m "feat: token 估算工具"
```

---

### Task 4: 哈希、URL 规范化与文件名工具

**Files:**
- Create: `seckb/utils/hashing.py`
- Test: `tests/test_hashing.py`

- [ ] **Step 1: 写失败测试**

`tests/test_hashing.py`：

```python
from pathlib import Path

from seckb.utils.hashing import normalize_url, sha256_file, slugify


def test_sha256_file(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    assert sha256_file(f) == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_normalize_url_strips_tracking_and_fragment():
    url = "HTTPS://Example.COM/post/?utm_source=x&id=42#section"
    assert normalize_url(url) == "https://example.com/post?id=42"


def test_slugify_ascii():
    assert slugify("SQLMap Usage Notes!") == "sqlmap-usage-notes"


def test_slugify_chinese_falls_back():
    assert slugify("永恒之蓝利用笔记") == "untitled"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_hashing.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.utils.hashing'`

- [ ] **Step 3: 写最小实现**

`seckb/utils/hashing.py`：

```python
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"spm", "from", "ref", "source", "share_token"}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    path = re.sub(r"/+", "/", parts.path) or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower() in _TRACKING_KEYS or k.lower().startswith(_TRACKING_PREFIXES))
    ]
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def slugify(title: str, max_len: int = 60) -> str:
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")
    return slug[:max_len].strip("-") or "untitled"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_hashing.py -v`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/utils/hashing.py tests/test_hashing.py
git commit -m "feat: 哈希/URL/文件名工具"
```

---

### Task 5: SimHash 近似去重工具

**Files:**
- Create: `seckb/utils/simhash.py`
- Test: `tests/test_simhash.py`

- [ ] **Step 1: 写失败测试**

`tests/test_simhash.py`：

```python
from seckb.utils.simhash import from_signed64, hamming, simhash64, to_signed64

BASE = (
    "the quick brown fox jumps over the lazy dog while the security team "
    "monitors network traffic for suspicious activity around the perimeter "
    "and the analyst writes a detailed report about the incident response"
)


def test_identical_text_zero_distance():
    assert hamming(simhash64(BASE), simhash64(BASE)) == 0


def test_small_change_small_distance():
    changed = BASE.replace("quick", "slow")
    assert hamming(simhash64(BASE), simhash64(changed)) <= 8


def test_signed64_roundtrip():
    h = simhash64(BASE)
    assert from_signed64(to_signed64(h)) == h


def test_empty_text():
    assert simhash64("") == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_simhash.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.utils.simhash'`

- [ ] **Step 3: 写最小实现**

`seckb/utils/simhash.py`：

```python
from __future__ import annotations

import hashlib
import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _hash64(token: str) -> int:
    return int.from_bytes(hashlib.md5(token.encode("utf-8")).digest()[:8], "big")


def simhash64(text: str, shingle: int = 3) -> int:
    tokens = _tokens(text)
    if not tokens:
        return 0
    if len(tokens) < shingle:
        grams = [" ".join(tokens)]
    else:
        grams = [" ".join(tokens[i : i + shingle]) for i in range(len(tokens) - shingle + 1)]
    counts: dict[str, int] = {}
    for gram in grams:
        counts[gram] = counts.get(gram, 0) + 1
    vector = [0] * 64
    for gram, weight in counts.items():
        h = _hash64(gram)
        for i in range(64):
            vector[i] += weight if (h >> i) & 1 else -weight
    out = 0
    for i in range(64):
        if vector[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def to_signed64(h: int) -> int:
    return h - (1 << 64) if h >= (1 << 63) else h


def from_signed64(h: int) -> int:
    return h + (1 << 64) if h < 0 else h
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_simhash.py -v`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/utils/simhash.py tests/test_simhash.py
git commit -m "feat: SimHash 近似去重工具"
```

---

### Task 6: 数据模型与数据库迁移

**Files:**
- Create: `seckb/models.py`
- Create: `seckb/db/__init__.py`（空文件）
- Create: `seckb/db/connection.py`
- Create: `seckb/db/migrate.py`
- Create: `seckb/db/migrations/0001_initial.sql`
- Create: `tests/conftest.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: 写失败测试**

`tests/test_db.py`：

```python
import sqlite3

from seckb.db.connection import init_db
from seckb.models import Asset, ChunkDraft, SnippetDraft


def test_init_db_creates_dirs_and_tables(kb):
    assert kb.settings.db_path.exists()
    names = {
        row["name"]
        for row in kb.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for expected in {
        "assets",
        "chunks",
        "snippets",
        "entities",
        "asset_entities",
        "books",
        "posts",
        "chunks_fts",
    }:
        assert expected in names


def test_migrate_is_idempotent(kb):
    from seckb.db.migrate import migrate

    assert kb.conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert migrate(kb.conn) == 1


def test_foreign_key_cascade(kb):
    conn = kb.conn
    conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at) VALUES('post','t','abc','markdown','now')"
    )
    asset_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO chunks(asset_id, seq, token_count, content_md) VALUES(?, 0, 5, 'hello')",
        (asset_id,),
    )
    conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
    count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert count == 0


def test_models_defaults():
    asset = Asset(type="post", title="t", sha256="x", format="markdown")
    assert asset.tags == []
    assert asset.status == "ok"
    assert asset.lang == "zh"
    assert ChunkDraft(seq=0, heading_path="", content="a", token_count=1).seq == 0
    assert SnippetDraft(kind="command", lang="bash", content="ls").tool is None


def test_init_db_twice_is_safe(kb):
    conn2 = init_db(kb.root)
    assert conn2.execute("PRAGMA user_version").fetchone()[0] == 1
    conn2.close()
```

`tests/conftest.py`：

```python
from __future__ import annotations

from pathlib import Path

import pytest

from seckb.config import Settings
from seckb.db.connection import init_db


class KB:
    root: Path
    settings: Settings
    conn: object


@pytest.fixture
def kb(tmp_path: Path):
    instance = KB()
    instance.root = tmp_path / "SecurityKB"
    instance.settings = Settings(
        kb_root=instance.root,
        taxonomy={
            "directions": {
                "web-security": ["sql注入", "xss", "web"],
                "pentest": ["渗透", "提权"],
            },
            "tools": ["nmap", "sqlmap", "nuclei"],
        },
    )
    instance.conn = init_db(instance.root)
    yield instance
    instance.conn.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.db'`

- [ ] **Step 3: 写最小实现**

`seckb/models.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Asset:
    type: str
    title: str
    sha256: str
    format: str
    size: int = 0
    lang: str = "zh"
    source: str = "manual"
    source_url: str | None = None
    path: str | None = None
    md_path: str | None = None
    simhash: int | None = None
    published_at: str | None = None
    tags: list[str] = field(default_factory=list)
    category: str | None = None
    status: str = "ok"


@dataclass
class ChunkDraft:
    seq: int
    heading_path: str
    content: str
    token_count: int


@dataclass
class SnippetDraft:
    kind: str
    lang: str | None
    content: str
    context: str = ""
    tool: str | None = None
```

`seckb/db/__init__.py`（空）

`seckb/db/migrate.py`：

```python
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME_RE = re.compile(r"^(\d{4})_.*\.sql$")


def _migrations() -> list[tuple[int, Path]]:
    items: list[tuple[int, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = _NAME_RE.match(path.name)
        if match:
            items.append((int(match.group(1)), path))
    return items


def migrate(conn: sqlite3.Connection) -> int:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version, path in _migrations():
        if version <= current:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {version}")
        current = version
    conn.commit()
    return current
```

`seckb/db/connection.py`：

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

from seckb.db.migrate import migrate

KB_DIRS = [
    "inbox",
    "books",
    "posts/zh",
    "posts/en",
    "repos",
    "vulndb",
    "ctf",
    "standards",
    "meta/logs",
    "meta/snapshots",
    "meta/tmp",
]


def open_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(kb_root: Path) -> sqlite3.Connection:
    for rel in KB_DIRS:
        (kb_root / rel).mkdir(parents=True, exist_ok=True)
    conn = open_db(kb_root / "meta" / "catalog.db")
    migrate(conn)
    return conn
```

`seckb/db/migrations/0001_initial.sql`：

```sql
CREATE TABLE assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  lang TEXT NOT NULL DEFAULT 'zh',
  source TEXT NOT NULL DEFAULT 'manual',
  source_url TEXT,
  path TEXT,
  md_path TEXT,
  sha256 TEXT NOT NULL UNIQUE,
  simhash INTEGER,
  size INTEGER NOT NULL DEFAULT 0,
  format TEXT NOT NULL,
  published_at TEXT,
  imported_at TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  category TEXT,
  status TEXT NOT NULL DEFAULT 'ok'
);
CREATE INDEX idx_assets_type ON assets(type);
CREATE INDEX idx_assets_simhash ON assets(simhash);

CREATE TABLE chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  heading_path TEXT NOT NULL DEFAULT '',
  page_from INTEGER,
  page_to INTEGER,
  token_count INTEGER NOT NULL,
  content_md TEXT NOT NULL,
  UNIQUE(asset_id, seq)
);
CREATE INDEX idx_chunks_asset ON chunks(asset_id);

CREATE TABLE snippets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  chunk_id INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
  kind TEXT NOT NULL,
  lang TEXT,
  tool TEXT,
  content TEXT NOT NULL,
  context TEXT
);

CREATE TABLE entities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  canonical TEXT NOT NULL,
  UNIQUE(kind, canonical)
);

CREATE TABLE asset_entities (
  asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  weight REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (asset_id, entity_id)
);

CREATE TABLE books (
  asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
  isbn TEXT,
  authors TEXT,
  publisher TEXT,
  year INTEGER,
  pages INTEGER,
  edition TEXT,
  cover_path TEXT,
  reading_status TEXT NOT NULL DEFAULT 'unread'
);

CREATE TABLE posts (
  asset_id INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
  site TEXT,
  author TEXT,
  board TEXT,
  views INTEGER,
  replies INTEGER,
  original_html_path TEXT
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
  content,
  heading_path,
  asset_id UNINDEXED,
  tokenize = 'trigram'
);
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: `5 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/models.py seckb/db/ tests/conftest.py tests/test_db.py
git commit -m "feat: 数据模型与 SQLite 迁移框架"
```

---

### Task 7: HTML → Markdown 归一化

**Files:**
- Create: `seckb/pipeline/__init__.py`（空文件）
- Create: `seckb/pipeline/normalize.py`（本任务先实现 HTML 部分）
- Test: `tests/test_normalize.py`

- [ ] **Step 1: 写失败测试**

`tests/test_normalize.py`：

```python
from pathlib import Path

from seckb.pipeline.normalize import html_to_markdown


def test_html_to_markdown_extracts_title_and_strips_scripts(tmp_path: Path):
    html = """
    <html><head><title>SQL 注入实战</title>
    <script>alert(1)</script><style>p{color:red}</style></head>
    <body><h1>SQL 注入实战</h1>
    <p>这是第一段内容，讲述 union 注入的基本原理与利用方式。</p>
    <p>这是第二段内容，给出防护建议与修复方案，供读者参考实践。</p>
    </body></html>
    """
    title, md = html_to_markdown(html, base_dir=tmp_path, images_dir=None)
    assert title == "SQL 注入实战"
    assert "# SQL 注入实战" in md
    assert "<script>" not in md
    assert "union 注入" in md


def test_html_images_localized_with_injected_fetcher(tmp_path: Path):
    html = """
    <html><head><title>PoC 展示</title></head><body>
    <p>下面给出一个可用于验证漏洞的截图，说明请求与响应之间的差异。</p>
    <img src="https://example.com/poc.png" alt="poc">
    <p>该截图展示了未授权访问成功返回敏感数据的完整过程与细节。</p>
    </body></html>
    """
    calls: list[str] = []

    def fake_fetcher(url: str) -> bytes:
        calls.append(url)
        return b"\x89PNG fake-bytes"

    title, md = html_to_markdown(
        html, base_dir=tmp_path, images_dir=tmp_path / "PoC.assets", fetcher=fake_fetcher
    )
    assert calls == ["https://example.com/poc.png"]
    assert (tmp_path / "PoC.assets" / "img-1.png").exists()
    assert "PoC.assets/img-1.png" in md
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_normalize.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.pipeline'`

- [ ] **Step 3: 写最小实现**

`seckb/pipeline/__init__.py`（空）

`seckb/pipeline/normalize.py`：

```python
from __future__ import annotations

import re
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from markdownify import markdownify
from readability import Document

Fetcher = Callable[[str], bytes]

_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


class ScannedPdfError(Exception):
    pass


def _default_fetcher(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "seckb/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def _read_image(src: str, base_dir: Path | None, fetcher: Fetcher) -> tuple[bytes | None, str]:
    if src.startswith(("http://", "https://")):
        data = fetcher(src)
        suffix = Path(urlsplit(src).path).suffix.lower() or ".img"
        return data, suffix
    if base_dir is not None:
        local = (base_dir / src).resolve()
        if local.is_file():
            return local.read_bytes(), local.suffix.lower() or ".img"
    return None, ""


def _localize_images(
    md: str,
    *,
    base_dir: Path | None,
    images_dir: Path,
    fetcher: Fetcher,
) -> str:
    images_dir.mkdir(parents=True, exist_ok=True)
    counter = 0

    def repl(match: re.Match) -> str:
        nonlocal counter
        alt, src = match.group(1), match.group(2)
        data, suffix = _read_image(src, base_dir, fetcher)
        if data is None:
            return match.group(0)
        counter += 1
        name = f"img-{counter}{suffix}"
        (images_dir / name).write_bytes(data)
        return f"![{alt}]({images_dir.name}/{name})"

    return _IMG_RE.sub(repl, md)


def html_to_markdown(
    html: str,
    *,
    base_dir: Path | None = None,
    images_dir: Path | None = None,
    fetcher: Fetcher | None = None,
) -> tuple[str, str]:
    doc = Document(html)
    title = (doc.title() or "").strip()
    body_html = doc.summary(html_partial=True)
    md = markdownify(body_html, heading_style="ATX", strip=["script", "style"])
    if images_dir is not None:
        md = _localize_images(
            md, base_dir=base_dir, images_dir=images_dir, fetcher=fetcher or _default_fetcher
        )
    return title, md.strip() + "\n"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_normalize.py -v`
Expected: `2 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/pipeline/ tests/test_normalize.py
git commit -m "feat: HTML 转 Markdown（含图片本地化）"
```

---

### Task 8: PDF / EPUB / Markdown 归一化与统一入口

**Files:**
- Modify: `seckb/pipeline/normalize.py`（追加函数）
- Test: `tests/test_normalize.py`（追加用例）

- [ ] **Step 1: 写失败测试（先把新导入合并进 `tests/test_normalize.py` 顶部 import 区，再追加用例）**

在文件顶部 import 区补充：

```python
import pymupdf
from ebooklib import epub

from seckb.pipeline.normalize import (
    ScannedPdfError,
    epub_to_markdown,
    normalize_to_markdown,
    pdf_to_markdown,
)
```

然后在文件末尾追加：

```python
def make_text_pdf(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "SQL Injection Handbook")
    page.insert_text((72, 96), "Chapter 1: UNION based injection basics")
    doc.save(str(path))
    doc.close()


def test_pdf_to_markdown_extracts_text(tmp_path: Path):
    pdf_path = tmp_path / "book.pdf"
    make_text_pdf(pdf_path)
    title, md = pdf_to_markdown(pdf_path)
    assert "UNION based injection" in md


def test_scanned_pdf_raises(tmp_path: Path):
    blank = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(blank))
    doc.close()
    try:
        pdf_to_markdown(blank)
    except ScannedPdfError:
        pass
    else:
        raise AssertionError("expected ScannedPdfError")


def test_epub_to_markdown(tmp_path: Path):
    epub_path = tmp_path / "notes.epub"
    book = epub.EpubBook()
    book.set_identifier("test-1")
    book.set_title("Crypto Notes")
    book.set_language("en")
    chapter = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
    chapter.content = (
        "<html><body><h1>Chapter 1</h1><p>Caesar cipher and frequency analysis.</p></body></html>"
    )
    book.add_item(chapter)
    book.toc = (chapter,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(epub_path), book)

    from seckb.pipeline.normalize import epub_to_markdown

    title, md = epub_to_markdown(epub_path)
    assert title == "Crypto Notes"
    assert "Caesar cipher" in md


def test_normalize_dispatch_markdown_passthrough(tmp_path: Path):
    src = tmp_path / "note.md"
    src.write_text("# 提权笔记\n\nLinux 提权常用方法汇总", encoding="utf-8")
    result = normalize_to_markdown(src, out_dir=tmp_path / "out", stem="s1")
    assert result.source_type == "markdown"
    assert result.title == "note"
    assert "提权笔记" in result.markdown
    assert result.needs_ocr is False


def test_normalize_dispatch_html(tmp_path: Path):
    src = tmp_path / "post.html"
    src.write_text(
        "<html><head><title>xss 利用</title></head>"
        "<body><p>反射型 xss 的基本利用链与绕过思路说明。</p></body></html>",
        encoding="utf-8",
    )
    result = normalize_to_markdown(src, out_dir=tmp_path / "out", stem="s2")
    assert result.source_type == "html"
    assert result.title == "xss 利用"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_normalize.py -v`
Expected: FAIL，`ImportError: cannot import name 'pdf_to_markdown'`

- [ ] **Step 3: 写最小实现（追加到 `seckb/pipeline/normalize.py` 末尾）**

```python
_EXT_FORMAT = {
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".pdf": "pdf",
    ".epub": "epub",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "markdown",
}

_PDF_MIN_CHARS_PER_PAGE = 30


class NormalizeResult:
    __slots__ = ("title", "markdown", "source_type", "needs_ocr")

    def __init__(self, title: str, markdown: str, source_type: str, needs_ocr: bool = False):
        self.title = title
        self.markdown = markdown
        self.source_type = source_type
        self.needs_ocr = needs_ocr


def guess_format(path: Path) -> str:
    return _EXT_FORMAT.get(path.suffix.lower(), "markdown")


def pdf_to_markdown(path: Path) -> tuple[str, str]:
    import pymupdf
    import pymupdf4llm

    doc = pymupdf.open(str(path))
    pages = doc.page_count
    text_len = sum(len(page.get_text()) for page in doc)
    if pages > 0 and text_len / pages < _PDF_MIN_CHARS_PER_PAGE:
        doc.close()
        raise ScannedPdfError(f"{path.name}: 疑似扫描版，需 OCR")
    title = (doc.metadata or {}).get("title") or ""
    md = pymupdf4llm.to_markdown(str(path))
    doc.close()
    return title.strip(), md.strip() + "\n"


def epub_to_markdown(path: Path) -> tuple[str, str]:
    from ebooklib import ITEM_DOCUMENT, epub

    book = epub.read_epub(str(path))
    title = ""
    metadata = book.get_metadata("DC", "title")
    if metadata:
        title = str(metadata[0][0])
    parts: list[str] = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        html = item.get_content().decode("utf-8", errors="replace")
        _, md = html_to_markdown(html)
        if md.strip():
            parts.append(md.strip())
    return title.strip(), "\n\n".join(parts) + "\n"


def normalize_to_markdown(
    src: Path,
    *,
    out_dir: Path,
    stem: str,
    fetcher: Fetcher | None = None,
) -> NormalizeResult:
    fmt = guess_format(src)
    if fmt == "html":
        html = src.read_text(encoding="utf-8", errors="replace")
        images_dir = out_dir / f"{stem}.assets" if _IMG_RE.search(html) else None
        title, md = html_to_markdown(
            html, base_dir=src.parent, images_dir=images_dir, fetcher=fetcher
        )
        return NormalizeResult(title or src.stem, md, "html")
    if fmt == "pdf":
        try:
            title, md = pdf_to_markdown(src)
        except ScannedPdfError:
            return NormalizeResult(src.stem, "", "pdf", needs_ocr=True)
        return NormalizeResult(title or src.stem, md, "pdf")
    if fmt == "epub":
        title, md = epub_to_markdown(src)
        return NormalizeResult(title or src.stem, md, "epub")
    md = src.read_text(encoding="utf-8", errors="replace")
    return NormalizeResult(src.stem, md.strip() + "\n", "markdown")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_normalize.py -v`
Expected: `7 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/pipeline/normalize.py tests/test_normalize.py
git commit -m "feat: PDF/EPUB/Markdown 归一化与统一入口"
```

---

### Task 9: Markdown 标题感知切块

**Files:**
- Create: `seckb/pipeline/chunker.py`
- Test: `tests/test_chunker.py`

- [ ] **Step 1: 写失败测试**

`tests/test_chunker.py`：

```python
from seckb.pipeline.chunker import chunk_markdown


def test_heading_path_recorded():
    md = "# 文档标题\n\n开头段落。\n\n## 第一节\n\n第一节内容。\n\n### 小节\n\n小节内容。\n"
    chunks = chunk_markdown(md)
    paths = [c.heading_path for c in chunks]
    assert "文档标题 > 第一节" in paths
    assert "文档标题 > 第一节 > 小节" in paths


def test_long_section_splits_with_overlap():
    paragraphs = [f"para-{i} " + "alpha bravo charlie delta echo foxtrot golf hotel india juliet" for i in range(15)]
    md = "# 长文\n\n" + "\n\n".join(paragraphs) + "\n"
    chunks = chunk_markdown(md, target_tokens=60, max_tokens=100, overlap_tokens=24)
    assert len(chunks) >= 2
    seqs = [c.seq for c in chunks]
    assert seqs == list(range(len(chunks)))
    assert all(c.token_count <= 100 for c in chunks)
    second = chunks[1].content
    assert second.split("\n\n")[0].startswith("para-")


def test_every_chunk_has_content_and_count():
    md = "# A\n\nsome text here\n"
    chunks = chunk_markdown(md)
    assert chunks
    assert all(c.content.strip() for c in chunks)
    assert all(c.token_count > 0 for c in chunks)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_chunker.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.pipeline.chunker'`

- [ ] **Step 3: 写最小实现**

`seckb/pipeline/chunker.py`：

```python
from __future__ import annotations

import re

from seckb.models import ChunkDraft
from seckb.utils.tokens import estimate_tokens

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_PARA_SPLIT_RE = re.compile(r"\n{2,}")


def _split_sections(md: str) -> list[tuple[list[str], str]]:
    sections: list[tuple[list[str], str]] = []
    stack: list[tuple[int, str]] = []
    current_path: list[str] = []
    current_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if body:
            sections.append((list(current_path), body))

    for line in md.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            flush()
            current_lines = []
            level = len(match.group(1))
            stack = [(lvl, text) for lvl, text in stack if lvl < level]
            stack.append((level, match.group(2).strip()))
            current_path = [text for _, text in stack]
            current_lines.append(line)
        else:
            current_lines.append(line)
    flush()
    return sections


def _hard_split(text: str, max_tokens: int) -> list[str]:
    total = estimate_tokens(text)
    approx_chars = max(1, int(len(text) * max_tokens / total))
    return [text[i : i + approx_chars] for i in range(0, len(text), approx_chars)]


def _split_long(text: str, target_tokens: int, max_tokens: int) -> list[str]:
    paragraphs = [p for p in _PARA_SPLIT_RE.split(text) if p.strip()]
    blocks: list[str] = []
    buffer: list[str] = []
    for paragraph in paragraphs:
        buffer.append(paragraph)
        if estimate_tokens("\n\n".join(buffer)) >= target_tokens:
            blocks.append("\n\n".join(buffer))
            buffer = []
    if buffer:
        blocks.append("\n\n".join(buffer))
    out: list[str] = []
    for block in blocks:
        if estimate_tokens(block) <= max_tokens:
            out.append(block)
        else:
            out.extend(_hard_split(block, max_tokens))
    return out


def _tail(text: str, overlap_tokens: int) -> str:
    paragraphs = [p for p in _PARA_SPLIT_RE.split(text) if p.strip()]
    tail: list[str] = []
    for paragraph in reversed(paragraphs):
        candidate = "\n\n".join([paragraph, *reversed(tail)])
        if tail and estimate_tokens(candidate) > overlap_tokens:
            break
        tail.append(paragraph)
    return "\n\n".join(reversed(tail))


def chunk_markdown(
    md: str,
    *,
    target_tokens: int = 700,
    max_tokens: int = 1000,
    overlap_tokens: int = 80,
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    seq = 0
    for path, body in _split_sections(md):
        pieces = _split_long(body, target_tokens, max_tokens) if estimate_tokens(body) > max_tokens else [body]
        previous_tail = ""
        for piece in pieces:
            content = piece
            if previous_tail:
                candidate = previous_tail + "\n\n" + piece
                if estimate_tokens(candidate) <= max_tokens:
                    content = candidate
            drafts.append(
                ChunkDraft(
                    seq=seq,
                    heading_path=" > ".join(path),
                    content=content,
                    token_count=estimate_tokens(content),
                )
            )
            seq += 1
            previous_tail = _tail(piece, overlap_tokens)
    return drafts
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_chunker.py -v`
Expected: `3 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/pipeline/chunker.py tests/test_chunker.py
git commit -m "feat: Markdown 标题感知切块（带重叠）"
```

---

### Task 10: 规则抽取（代码片段 / CVE / 工具 / ATT&CK）

**Files:**
- Create: `seckb/pipeline/rules.py`
- Test: `tests/test_rules.py`

- [ ] **Step 1: 写失败测试**

`tests/test_rules.py`：

```python
from seckb.pipeline.rules import (
    extract_attack_ids,
    extract_cves,
    extract_snippets,
    extract_tools,
)


def test_extract_cves_sorted_unique():
    text = "利用 cve-2021-44228 与 CVE-2021-44228，还有 CVE-2017-0144。"
    assert extract_cves(text) == ["CVE-2017-0144", "CVE-2021-44228"]


def test_extract_tools_word_boundary():
    text = "用 sqlmap 跑一下，配合 nmap 扫描；sqlmaptool 不算。"
    assert extract_tools(text, ["sqlmap", "nmap"]) == ["nmap", "sqlmap"]


def test_extract_attack_ids():
    text = "T1059.001 PowerShell, T1003 credential dumping"
    assert extract_attack_ids(text) == ["T1003", "T1059.001"]


def test_extract_snippets_kinds():
    md = """
```bash
nmap -sV -p- 10.0.0.1
```
```bash
for i in $(seq 1 10); do echo $i; done
echo done
```
```python
# payload: reverse shell
import socket
```
```php
<?php echo 1; ?>
```
"""
    snippets = extract_snippets(md)
    kinds = [(s.kind, s.lang) for s in snippets]
    assert kinds == [
        ("oneliner", "bash"),
        ("command", "bash"),
        ("payload", "python"),
        ("code", "php"),
    ]
    assert "nmap -sV" in snippets[0].content
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rules.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.pipeline.rules'`

- [ ] **Step 3: 写最小实现**

`seckb/pipeline/rules.py`：

```python
from __future__ import annotations

import re

from seckb.models import SnippetDraft

CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
ATTACK_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b")
_FENCE_RE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
_PAYLOAD_MARK_RE = re.compile(r"^\s*(?:#|//|<!--)\s*(payload|exploit|poc)", re.IGNORECASE)

SHELL_LANGS = {"bash", "sh", "shell", "zsh", "powershell", "ps1", "cmd", "bat", "console"}
CODE_LANGS = {
    "python", "py", "php", "javascript", "js", "typescript", "ts",
    "java", "csharp", "cs", "go", "ruby", "rb", "perl", "c", "cpp",
}


def extract_cves(text: str) -> list[str]:
    return sorted({match.group(0).upper() for match in CVE_RE.finditer(text)})


def extract_attack_ids(text: str) -> list[str]:
    return sorted({match.group(0).upper() for match in ATTACK_RE.finditer(text)})


def extract_tools(text: str, tools: list[str]) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    for tool in tools:
        pattern = rf"(?<![a-z0-9_-]){re.escape(tool.lower())}(?![a-z0-9_-])"
        if re.search(pattern, lower):
            found.append(tool)
    return sorted(found)


def extract_snippets(md: str) -> list[SnippetDraft]:
    snippets: list[SnippetDraft] = []
    for match in _FENCE_RE.finditer(md):
        lang = match.group(1).strip().lower() or None
        body = match.group(2).strip("\n")
        if not body.strip():
            continue
        kind = "code"
        if lang in SHELL_LANGS:
            kind = "oneliner" if "\n" not in body.strip() else "command"
        elif lang in CODE_LANGS:
            kind = "payload" if _PAYLOAD_MARK_RE.match(body) else "code"
        snippets.append(SnippetDraft(kind=kind, lang=lang, content=body))
    return snippets
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_rules.py -v`
Expected: `4 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/pipeline/rules.py tests/test_rules.py
git commit -m "feat: 规则抽取（片段/CVE/工具/ATT&CK）"
```

---

### Task 11: 去重查询

**Files:**
- Create: `seckb/pipeline/dedupe.py`
- Test: `tests/test_dedupe.py`

- [ ] **Step 1: 写失败测试**

`tests/test_dedupe.py`：

```python
from seckb.pipeline.dedupe import find_by_sha256, find_near_duplicate
from seckb.utils.simhash import simhash64, to_signed64

TEXT = (
    "以太坊智能合约审计中常见的重入漏洞利用方式与 Solidity 转账函数调用顺序 "
    "密切相关，开发者在编写提现逻辑时必须先更新余额再进行外部调用。"
) * 3


def test_find_by_sha256(kb):
    kb.conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at) VALUES('post','t','deadbeef','markdown','now')"
    )
    assert find_by_sha256(kb.conn, "deadbeef") == 1
    assert find_by_sha256(kb.conn, "unknown") is None


def test_find_near_duplicate(kb):
    near = TEXT + "补充一句无关紧要的话。"
    far = "Kubernetes 集群安全加固清单：RBAC 最小权限、网络策略、镜像签名与审计日志。"
    kb.conn.execute(
        "INSERT INTO assets(type, title, sha256, simhash, format, imported_at) VALUES('post','t','a1',?,'markdown','now')",
        (to_signed64(simhash64(TEXT)),),
    )
    assert find_near_duplicate(kb.conn, near) == 1
    assert find_near_duplicate(kb.conn, far) is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dedupe.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.pipeline.dedupe'`

- [ ] **Step 3: 写最小实现**

`seckb/pipeline/dedupe.py`：

```python
from __future__ import annotations

import sqlite3

from seckb.utils.simhash import from_signed64, hamming, simhash64


def find_by_sha256(conn: sqlite3.Connection, sha256: str) -> int | None:
    row = conn.execute("SELECT id FROM assets WHERE sha256 = ?", (sha256,)).fetchone()
    return row["id"] if row else None


def find_near_duplicate(conn: sqlite3.Connection, text: str, *, threshold: int = 3) -> int | None:
    fingerprint = simhash64(text)
    rows = conn.execute("SELECT id, simhash FROM assets WHERE simhash IS NOT NULL")
    for row in rows:
        if hamming(from_signed64(row["simhash"]), fingerprint) <= threshold:
            return row["id"]
    return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dedupe.py -v`
Expected: `2 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/pipeline/dedupe.py tests/test_dedupe.py
git commit -m "feat: 去重查询（sha256 + SimHash）"
```

---

### Task 12: FTS5 索引与检索门面

**Files:**
- Create: `seckb/indexer/__init__.py`（空文件）
- Create: `seckb/indexer/fts.py`
- Create: `seckb/search.py`
- Test: `tests/test_fts.py`

- [ ] **Step 1: 写失败测试**

`tests/test_fts.py`：

```python
from seckb.indexer import fts
from seckb.search import search


def add_asset(conn, *, title: str, content: str, asset_type: str = "post") -> int:
    conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at) VALUES(?,?,?,?,?)",
        (asset_type, title, title.encode("utf-8").hex()[:16], "markdown", "now"),
    )
    asset_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO chunks(asset_id, seq, heading_path, token_count, content_md) VALUES(?,0,'',10,?)",
        (asset_id, content),
    )
    fts.index_asset(conn, asset_id)
    conn.commit()
    return asset_id


def test_chinese_substring_search(kb):
    add_asset(kb.conn, title="永恒之蓝笔记", content="MS17-010 永恒之蓝漏洞利用与防护要点")
    hits = search(kb.conn, "永恒之蓝")
    assert len(hits) == 1
    assert hits[0].title == "永恒之蓝笔记"
    assert hits[0].asset_id == 1


def test_english_search(kb):
    add_asset(kb.conn, title="sqlmap cheat", content="sqlmap tamper scripts for waf bypass")
    hits = search(kb.conn, "tamper")
    assert len(hits) == 1


def test_type_filter(kb):
    add_asset(kb.conn, title="A", content="union injection basics", asset_type="book")
    add_asset(kb.conn, title="B", content="union injection notes", asset_type="post")
    assert len(search(kb.conn, "union", asset_type="book")) == 1
    assert len(search(kb.conn, "union")) == 2


def test_short_query_returns_empty(kb):
    add_asset(kb.conn, title="A", content="waf bypass")
    assert search(kb.conn, "ab") == []


def test_rebuild(kb):
    add_asset(kb.conn, title="A", content="kubernetes escape")
    count = fts.rebuild(kb.conn)
    assert count == 1
    assert len(search(kb.conn, "kubernetes")) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_fts.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.indexer'`

- [ ] **Step 3: 写最小实现**

`seckb/indexer/__init__.py`（空）

`seckb/indexer/fts.py`：

```python
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

_INTERNAL_QUOTE = re.compile(r'"')


@dataclass
class SearchHit:
    asset_id: int
    chunk_id: int
    title: str
    heading_path: str
    snippet: str
    score: float


def build_query(raw: str) -> str:
    terms = [t for t in re.split(r"\s+", raw.strip()) if len(t) >= 3]
    if not terms:
        return ""
    return " AND ".join('"' + _INTERNAL_QUOTE.sub('""', t) + '"' for t in terms)


def index_asset(conn: sqlite3.Connection, asset_id: int) -> None:
    conn.execute(
        """
        INSERT INTO chunks_fts(rowid, content, heading_path, asset_id)
        SELECT c.id, c.content_md, c.heading_path, c.asset_id
        FROM chunks c WHERE c.asset_id = ?
        """,
        (asset_id,),
    )


def rebuild(conn: sqlite3.Connection) -> int:
    conn.execute("DELETE FROM chunks_fts")
    conn.execute(
        """
        INSERT INTO chunks_fts(rowid, content, heading_path, asset_id)
        SELECT c.id, c.content_md, c.heading_path, c.asset_id FROM chunks c
        """
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 10,
    asset_type: str | None = None,
) -> list[SearchHit]:
    match = build_query(query)
    if not match:
        return []
    sql = """
        SELECT f.asset_id, f.rowid AS chunk_id, a.title, f.heading_path,
               snippet(chunks_fts, 0, '[', ']', '…', 16) AS snip,
               bm25(chunks_fts, 10.0, 1.0) AS score
        FROM chunks_fts f
        JOIN assets a ON a.id = f.asset_id
        WHERE chunks_fts MATCH ?
    """
    params: list = [match]
    if asset_type:
        sql += " AND a.type = ?"
        params.append(asset_type)
    sql += " ORDER BY score LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [
        SearchHit(
            asset_id=row["asset_id"],
            chunk_id=row["chunk_id"],
            title=row["title"],
            heading_path=row["heading_path"] or "",
            snippet=row["snip"] or "",
            score=float(row["score"]),
        )
        for row in rows
    ]
```

`seckb/search.py`：

```python
from __future__ import annotations

import sqlite3

from seckb.indexer.fts import SearchHit, search as fts_search


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    asset_type: str | None = None,
    limit: int = 10,
) -> list[SearchHit]:
    return fts_search(conn, query, asset_type=asset_type, limit=limit)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_fts.py -v`
Expected: `5 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/indexer/ seckb/search.py tests/test_fts.py
git commit -m "feat: FTS5 索引与检索门面"
```

---

### Task 13: 导入器（inbox → 归档入库）

**Files:**
- Create: `seckb/pipeline/importer.py`
- Test: `tests/test_importer.py`

- [ ] **Step 1: 写失败测试**

`tests/test_importer.py`：

```python
from pathlib import Path

from seckb.pipeline.importer import import_file, scan_inbox


def write_post(tmp_path: Path, name: str = "post.md", body: str = "") -> Path:
    text = body or (
        "# 永恒之蓝利用笔记\n\n"
        "MS17-010 永恒之蓝漏洞，使用 nmap 扫描后利用 msf 模块 getshell。\n\n"
        "```bash\nnmap -sV -p445 10.0.0.1\n```\n"
    )
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_import_markdown_post(kb, tmp_path: Path):
    src = write_post(tmp_path)
    report = import_file(kb.conn, kb.settings, src)
    assert report.status == "imported"
    row = kb.conn.execute("SELECT * FROM assets WHERE id = ?", (report.asset_id,)).fetchone()
    assert row["type"] == "post"
    assert row["lang"] == "zh"
    assert row["path"] == row["md_path"]
    assert "永恒之蓝" in row["title"]
    assert not src.exists()
    md_files = list((kb.root / "posts" / "zh").glob("*.md"))
    assert len(md_files) == 1


def test_import_creates_chunks_and_snippets(kb, tmp_path: Path):
    report = import_file(kb.conn, kb.settings, write_post(tmp_path))
    chunk_count = kb.conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE asset_id = ?", (report.asset_id,)
    ).fetchone()[0]
    snippet = kb.conn.execute(
        "SELECT * FROM snippets WHERE asset_id = ?", (report.asset_id,)
    ).fetchone()
    assert chunk_count >= 1
    assert snippet["kind"] == "oneliner"
    assert "nmap -sV" in snippet["content"]


def test_import_links_entities(kb, tmp_path: Path):
    report = import_file(kb.conn, kb.settings, write_post(tmp_path))
    rows = kb.conn.execute(
        """SELECT e.kind, e.name FROM asset_entities ae
           JOIN entities e ON e.id = ae.entity_id WHERE ae.asset_id = ?""",
        (report.asset_id,),
    ).fetchall()
    pairs = {(row["kind"], row["name"]) for row in rows}
    assert ("tool", "nmap") in pairs


def test_duplicate_by_sha256(kb, tmp_path: Path):
    src_a = write_post(tmp_path, "a.md")
    first = import_file(kb.conn, kb.settings, src_a)
    src_b = write_post(tmp_path, "b.md")
    second = import_file(kb.conn, kb.settings, src_b)
    assert second.status == "duplicated"
    assert second.asset_id == first.asset_id
    assert src_b.exists()


def test_scanned_pdf_needs_ocr(kb, tmp_path: Path):
    import pymupdf

    blank = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(blank))
    doc.close()
    report = import_file(kb.conn, kb.settings, blank)
    assert report.status == "needs_ocr"
    assert blank.exists()


def test_scan_inbox(kb, tmp_path: Path):
    write_post(kb.root / "inbox", "one.md", "# 提权笔记\n\nlinux 提权常见手法：suid、sudo、cron。")
    write_post(kb.root / "inbox", "two.md", "# XSS 笔记\n\n反射型 xss 的利用与绕过，配合 csrf 链式利用。")
    reports = scan_inbox(kb.conn, kb.settings)
    assert [r.status for r in reports] == ["imported", "imported"]
    assert not list((kb.root / "inbox").iterdir())


def test_book_gets_sidecar_meta(kb, tmp_path: Path):
    import pymupdf

    pdf = tmp_path / "handbook.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Web Security Handbook")
    page.insert_text((72, 96), "Chapter 1: xss and sql injection basics")
    doc.save(str(pdf))
    doc.close()
    report = import_file(kb.conn, kb.settings, pdf)
    assert report.status == "imported"
    row = kb.conn.execute("SELECT * FROM assets WHERE id = ?", (report.asset_id,)).fetchone()
    assert row["type"] == "book"
    assert row["category"] == "web-security"
    meta_files = list((kb.root / "books" / "web-security").glob("*.meta.json"))
    assert len(meta_files) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_importer.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.pipeline.importer'`

- [ ] **Step 3: 写最小实现**

`seckb/pipeline/importer.py`：

```python
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from seckb.config import Settings
from seckb.indexer import fts
from seckb.pipeline import rules
from seckb.pipeline.chunker import chunk_markdown
from seckb.pipeline.dedupe import find_by_sha256, find_near_duplicate
from seckb.pipeline.normalize import normalize_to_markdown
from seckb.utils.hashing import sha256_file, slugify
from seckb.utils.simhash import simhash64, to_signed64

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$")


@dataclass
class ImportReport:
    status: str
    asset_id: int | None = None
    path: str | None = None


def _first_h1(markdown: str) -> str:
    for line in markdown.splitlines():
        match = _H1_RE.match(line)
        if match:
            return match.group(1).strip().rstrip("#").strip()
    return ""


def detect_lang(text: str) -> str:
    if not text:
        return "en"
    cjk = len(_CJK_RE.findall(text))
    return "zh" if cjk / max(len(text), 1) > 0.05 else "en"


def guess_direction(title: str, text: str, directions: dict[str, list[str]]) -> str:
    sample = (title + "\n" + text[:2000]).lower()
    best, best_score = "misc", 0
    for direction, keywords in directions.items():
        score = sum(1 for keyword in keywords if keyword.lower() in sample)
        if score > best_score:
            best, best_score = direction, score
    return best


def _link_entity(conn: sqlite3.Connection, asset_id: int, kind: str, name: str) -> None:
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


def import_file(
    conn: sqlite3.Connection,
    settings: Settings,
    src: Path,
    *,
    asset_type: str | None = None,
) -> ImportReport:
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(src)

    orig_size = src.stat().st_size
    sha = sha256_file(src)
    existing = find_by_sha256(conn, sha)
    if existing:
        return ImportReport("duplicated", existing, None)

    tmp_dir = settings.kb_root / "meta" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{sha[:8]}-{slugify(src.stem)}"

    result = normalize_to_markdown(src, out_dir=tmp_dir, stem=stem)
    if result.needs_ocr:
        return ImportReport("needs_ocr", None, str(src))

    near = find_near_duplicate(conn, result.markdown)
    if near is not None:
        return ImportReport("duplicated", near, None)

    kind = asset_type or ("book" if result.source_type in {"pdf", "epub"} else "post")
    title = result.title
    if result.source_type == "markdown":
        title = _first_h1(result.markdown) or result.title
    direction = guess_direction(
        title, result.markdown, settings.taxonomy.get("directions", {})
    )
    lang = detect_lang(result.markdown)

    rel_dir = Path("books") / direction if kind == "book" else Path("posts") / lang
    out_dir = settings.kb_root / rel_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    tmp_images = tmp_dir / f"{stem}.assets"
    if tmp_images.is_dir():
        shutil.move(str(tmp_images), str(out_dir / f"{stem}.assets"))

    md_path = out_dir / f"{stem}.md"
    md_path.write_text(result.markdown, encoding="utf-8")
    md_rel = md_path.relative_to(settings.kb_root).as_posix()

    if result.source_type == "markdown":
        orig_rel = md_rel
        src.unlink()
    else:
        orig_path = out_dir / f"{stem}{src.suffix.lower()}"
        shutil.move(str(src), str(orig_path))
        orig_rel = orig_path.relative_to(settings.kb_root).as_posix()

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cursor = conn.execute(
        """
        INSERT INTO assets(type, title, lang, source, source_url, path, md_path,
                           sha256, simhash, size, format, imported_at, tags, category, status)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            kind,
            title,
            lang,
            "manual",
            None,
            orig_rel,
            md_rel,
            sha,
            to_signed64(simhash64(result.markdown)),
            orig_size,
            result.source_type,
            now,
            "[]",
            direction,
            "ok",
        ),
    )
    asset_id = cursor.lastrowid

    for draft in chunk_markdown(result.markdown):
        conn.execute(
            "INSERT INTO chunks(asset_id, seq, heading_path, token_count, content_md) VALUES(?,?,?,?,?)",
            (asset_id, draft.seq, draft.heading_path, draft.token_count, draft.content),
        )

    for snippet in rules.extract_snippets(result.markdown):
        conn.execute(
            "INSERT INTO snippets(asset_id, kind, lang, tool, content) VALUES(?,?,?,?,?)",
            (asset_id, snippet.kind, snippet.lang, snippet.tool, snippet.content),
        )

    for cve in rules.extract_cves(result.markdown):
        _link_entity(conn, asset_id, "cve", cve)
    for attack_id in rules.extract_attack_ids(result.markdown):
        _link_entity(conn, asset_id, "attack", attack_id)
    for tool in rules.extract_tools(result.markdown, settings.taxonomy.get("tools", [])):
        _link_entity(conn, asset_id, "tool", tool)

    if kind == "book":
        meta = {
            "title": title,
            "sha256": sha,
            "direction": direction,
            "imported_at": now,
        }
        (out_dir / f"{stem}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        conn.execute("INSERT INTO books(asset_id) VALUES(?)", (asset_id,))

    fts.index_asset(conn, asset_id)
    conn.commit()
    return ImportReport("imported", asset_id, md_rel)


def scan_inbox(conn: sqlite3.Connection, settings: Settings) -> list[ImportReport]:
    inbox = settings.kb_root / "inbox"
    reports: list[ImportReport] = []
    for entry in sorted(inbox.iterdir()):
        if entry.is_file():
            reports.append(import_file(conn, settings, entry))
    return reports
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_importer.py -v`
Expected: `7 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/pipeline/importer.py tests/test_importer.py
git commit -m "feat: 导入器（归一化/切块/片段/实体/归档）"
```

---

### Task 14: CLI（init / import / scan / search / stats）

**Files:**
- Create: `seckb/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: 写失败测试**

`tests/test_cli.py`：

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


def test_cli_init_import_search_stats(tmp_path: Path):
    cfg = write_config(tmp_path)
    result = runner.invoke(app, ["--config", str(cfg), "init"])
    assert result.exit_code == 0

    src = tmp_path / "post.md"
    src.write_text("# 永恒之蓝\n\nMS17-010 利用与防护笔记。", encoding="utf-8")
    result = runner.invoke(app, ["--config", str(cfg), "import", str(src)])
    assert result.exit_code == 0
    assert "imported" in result.output

    result = runner.invoke(app, ["--config", str(cfg), "search", "永恒之蓝"])
    assert result.exit_code == 0
    assert "永恒之蓝" in result.output

    result = runner.invoke(app, ["--config", str(cfg), "stats"])
    assert result.exit_code == 0
    assert "post" in result.output
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'seckb.cli'`

- [ ] **Step 3: 写最小实现**

`seckb/cli.py`：

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from seckb.config import Settings, load_settings
from seckb.db.connection import init_db
from seckb.pipeline.importer import import_file, scan_inbox
from seckb.search import search as search_kb

app = typer.Typer(help="seckb - 面向 AI agent 的本地网络安全知识库", no_args_is_help=True)
console = Console()


def _open(settings: Settings) -> sqlite3.Connection:
    return init_db(settings.kb_root)


@app.callback()
def app_callback(
    ctx: typer.Context,
    config: Path = typer.Option(None, "--config", help="配置目录（含 settings.yaml / taxonomy.yaml）"),
) -> None:
    ctx.obj = load_settings(config)


@app.command()
def init(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    console.print(f"[green]知识库已初始化[/green] {settings.kb_root} (db: {settings.db_path})")
    conn.close()


@app.command("import")
def import_cmd(ctx: typer.Context, path: Path = typer.Argument(..., exists=True)) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    report = import_file(conn, settings, path)
    console.print(f"{report.status} asset_id={report.asset_id} path={report.path}")
    conn.close()


@app.command()
def scan(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    reports = scan_inbox(conn, settings)
    imported = sum(1 for r in reports if r.status == "imported")
    console.print(f"扫描完成：{len(reports)} 个文件，导入 {imported} 个")
    for report in reports:
        console.print(f"  {report.status} {report.path or ''}")
    conn.close()


@app.command()
def search(
    ctx: typer.Context,
    query: str = typer.Argument(...),
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    hits = search_kb(conn, query, limit=limit)
    table = Table(title=f"搜索：{query}（{len(hits)} 条）")
    table.add_column("id", width=6)
    table.add_column("标题", max_width=40)
    table.add_column("片段", max_width=60)
    for hit in hits:
        table.add_row(str(hit.asset_id), hit.title, hit.snippet)
    console.print(table)
    conn.close()


@app.command()
def stats(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj
    conn = _open(settings)
    table = Table(title="知识库统计")
    table.add_column("指标")
    table.add_column("数量", justify="right")
    for asset_type, count in conn.execute(
        "SELECT type, COUNT(*) AS c FROM assets GROUP BY type ORDER BY c DESC"
    ):
        table.add_row(f"assets.{asset_type}", str(count))
    for metric, sql in (
        ("chunks", "SELECT COUNT(*) FROM chunks"),
        ("snippets", "SELECT COUNT(*) FROM snippets"),
        ("entities", "SELECT COUNT(*) FROM entities"),
    ):
        table.add_row(metric, str(conn.execute(sql).fetchone()[0]))
    console.print(table)
    console.print(f"知识库位置：{settings.kb_root}")
    conn.close()


def main() -> None:
    app()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cli.py -v`
Expected: `1 passed`

- [ ] **Step 5: 提交**

```powershell
git add seckb/cli.py tests/test_cli.py
git commit -m "feat: CLI（init/import/scan/search/stats）"
```

---

### Task 15: 端到端验收与收尾

**Files:**
- Create: `tests/test_e2e.py`
- Modify: 依据 ruff 输出修正相关文件

- [ ] **Step 1: 写端到端测试**

`tests/test_e2e.py`：

```python
from pathlib import Path

from seckb.pipeline.importer import scan_inbox
from seckb.search import search


def test_full_pipeline(kb):
    inbox = kb.root / "inbox"
    (inbox / "one.md").write_text(
        "# 永恒之蓝复现\n\n使用 nmap 探测 445 端口，MS17-010 永恒之蓝可 getshell。\n\n"
        "```bash\nnmap -sV -p445 10.0.0.1\n```\n",
        encoding="utf-8",
    )
    (inbox / "two.html").write_text(
        "<html><head><title>XSS 绕过 WAF</title></head><body>"
        "<p>利用大小写混淆与注释分割绕过 waf 对 onerror 的拦截。</p></body></html>",
        encoding="utf-8",
    )
    reports = scan_inbox(kb.conn, kb.settings)
    assert all(r.status == "imported" for r in reports)

    hits = search(kb.conn, "永恒之蓝")
    assert hits and hits[0].asset_id == 1

    posts = list((kb.root / "posts").rglob("*.md"))
    assert len(posts) == 2

    snippet = kb.conn.execute("SELECT COUNT(*) FROM snippets").fetchone()[0]
    assert snippet >= 1
```

- [ ] **Step 2: 运行全量测试**

Run: `.venv\Scripts\python.exe -m pytest -v`
Expected: 全部通过（约 40 个用例）

- [ ] **Step 3: 运行 ruff 并修复**

Run: `.venv\Scripts\python.exe -m ruff check seckb tests`
Expected: 无错误；若有则逐条修复后重跑 Step 2。

> 执行记录（2026-09-13）：实际修复 13 处，涉及 `seckb/cli.py`（B008→`Annotated`）、`seckb/pipeline/importer.py`（UP017→`datetime.UTC`）、`seckb/pipeline/normalize.py`（UP035/RUF023）、`seckb/search.py`（I001）、`tests/test_db.py`（F401/PLC0208）、`tests/test_normalize.py`（F401/F811/RUF059）、`tests/test_e2e.py`（删除未使用 import）。行为均不变，修复后 50 passed + ruff clean。

- [ ] **Step 4: 真实知识库冒烟（手动）**

在仓库根执行（会在 D:\SecurityKB 建库并导入一个样例）：

```powershell
.venv\Scripts\python.exe -m seckb init
"# 冒烟测试`n`n这是 seckb 的第一条记录，关键词：永恒之蓝。" | Out-File -Encoding utf8 D:\SecurityKB\inbox\smoke.md
.venv\Scripts\python.exe -m seckb scan
.venv\Scripts\python.exe -m seckb search 永恒之蓝
.venv\Scripts\python.exe -m seckb stats
```

Expected: search 输出包含样例记录；stats 显示 post=1。

- [ ] **Step 5: 提交**

```powershell
git add tests/test_e2e.py seckb/ tests/
git commit -m "test: 端到端验收；P1a 数据管线完成"
```

---

## 后续计划（不在本计划内）

- **Plan P1b：采集与富化** — T1 连接器（GitHub/NVD/Exploit-DB/Vulhub/RSS）、sources 游标表、APScheduler 守护进程、云端 LLM 富化队列、知识卡片、bge-m3 向量化、Meilisearch 索引
- **Plan P1c：混合检索与 Agent 接口** — RRF 融合、MCP server（kb_search/kb_card/kb_get/kb_snippets）、FastAPI HTTP 接口、评测集（golden_queries）

## 本计划明确的取舍（YAGNI）

- 扫描版 PDF 只标记 `needs_ocr`，OCR（RapidOCR）留到后续计划
- 帖子页面的 `page_from/page_to` 字段预留但暂不填充
- `.mhtml` 支持、浏览器插件投递留到后续计划
- 导入的 `source/published_at` 暂为 manual/None，等 P1b 连接器写入
