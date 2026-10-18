# 参与贡献

先读一遍 README 的「为什么做」和「怎么设计」两节，能省掉大部分来回沟通。

## 这个项目的边界

- **第一消费对象是 AI Agent，人是维护者。** 面向人的功能（看板）是辅助，不要为了好看牺牲 Agent 侧的检索质量与 token 开销。
- **不做 RAG 问答。** Agent 自己就是 LLM，知识库只负责"高质量零售检索"。
- **不内置盗版书籍爬虫，不重分发任何内容。** 采集到的内容版权归原始来源。
- **仓库不含数据。** 数据落在 `SECKB_ROOT`（默认 `D:/SecurityKB`），由使用者自行采集。

## 开发环境

```bash
git clone https://github.com/xiabai2008/seckb.git
cd seckb
python -m venv .venv
.venv\Scripts\activate          # Windows；Linux/macOS 用 source .venv/bin/activate
pip install -e ".[dev]"
```

只跑代码与测试不需要 Ollama / Meilisearch / LLM Key —— 测试全部用 mock 与临时库，是自足的。

## 提交前必须过

```bash
pytest -q            # 全量测试
ruff check .         # lint（line-length 100）
```

CI 会在 Ubuntu 与 Windows 上跑同样这两条，两个平台都必须绿。

## 常见改动怎么做

### 新增一个采集源

1. 在 `seckb/connectors/` 加一个文件，实现统一接口（`fetch(cursor) -> items`），可参考 `nvd.py` / `rss.py`。
2. 在 `seckb/connectors/__init__.py` 注册类型。
3. 在 `config/sources.yaml` 加一段配置 —— **配置里要留可直接用的示例**，别人克隆下来就能跑。
4. 补 `tests/test_connector_<name>.py`，用录制的响应做回归（不要依赖真实网络）。

**检索内核不用动** —— 新增来源只是多一路数据，不是多一路检索。

### 调整检索

检索内核在 `seckb/retrieval.py`：多路召回 → RRF 融合 → 按预算取用。改动请一并考虑：

- **降级路径**：任何一路挂了都必须能继续返回结果，并把不可用通道写进 `degraded`。
- **token 开销**：`kb_search` 返回的是卡片级摘要，不要把正文塞进搜索结果。
- **评测**：跑 `seckb eval` 看命中率有没有退化；顺手在 `tests/eval/golden_queries.yaml` 补上你遇到的新场景。

### 改看板

`seckb/static/dashboard.html` 是单文件（HTML + CSS + JS），主题 token 集中在开头三个块里。改完在浏览器里两种主题（玄墨 / 纸本）都看一眼。

## 提交信息

沿用仓库现有风格：`类型: 中文说明`，类型取 `feat` / `fix` / `docs` / `test` / `chore` / `sources` / `perf`。

```
feat: MCP 新增 kb_services 工具（status/start 自愈检索后端，不开放 stop）
fix: NVD 改分窗拉取，游标只推进到完整窗口（修复静默丢数据）
```

一次提交只做一件事；行为和测试分开提交更便于回溯。

## 数据与隐私红线

提交前请自查，以下内容**永远不要进仓库**：

- `catalog.db`、`lancedb/`、`meili/` 等数据与索引
- 任何语料原件（PDF / EPUB / 抓取的 Markdown）
- API Key、`MEILI_MASTER_KEY`、`auth.json` 等凭据
- 你本机的绝对路径（用 `__file__` 推导或配置项代替）

`.gitignore` 已覆盖大部分，但**新加的目录请自己确认**。
