# seckb · 面向 AI Agent 的本地网络安全知识库

> 把安全知识预先采集、结构化，做成 **Agent 能秒查的形态**：本地、带出处、按 token 预算取用。

[![Python](https://img.shields.io/badge/python-3.12-3776ab?logo=python&logoColor=white)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-183%20passed-35d9a3)](tests/)
[![MCP](https://img.shields.io/badge/MCP-stdio%20server-8a63d2)](seckb/mcp_server.py)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Data](https://img.shields.io/badge/data-自行采集%20·%20仓库不含语料-f2b33d)](#数据从哪里来本仓库不提供数据)

**第一消费对象是 AI Agent，人是维护者。** 知识库不做 RAG 问答（Agent 自己就是 LLM），只负责一件事：让 Agent 用最少的上下文开销，拿到可信、带出处、可执行的答案。

---

## 为什么做

渗透 Agent 在信息收集、漏洞利用、绕过、横向的每一步都要"查资料"。没有本地知识库时，它只有两条路，都不好：

- **现搜网络** —— 慢（每次都要联网、翻页、清洗 HTML），贵（网页原文塞进上下文动辄几千 token），而且**不可信**：来源可能是过期的、抄错的，甚至是投毒的（已知有面向 Agent 的 Skill 投毒形态：描述全正向，恶意逻辑藏在指令步骤里）。
- **凭模型记忆** —— CVE 编号、工具参数、利用链细节记不准，版本一变就过期。

更要命的是**上下文经济学**：Agent 的上下文窗口是稀缺资源。如果把整篇文章塞进去，一次检索就吃掉几万 token，后续推理没有余量。真正需要的是"先给一张 200 token 的卡片判断相关性，相关再展开需要的切片"。

所以这个项目要解决的不是"数据不够多"，而是三件事：

1. **可信**：每条结果都带来源、日期、出处链接；CVE 带 CVSS / CWE / 是否在野利用。
2. **省 token**：卡片 / 切片 / 片段三级粒度，按预算取用，不整篇倒。
3. **快且离线**：检索核心全本地（SQLite + FTS5 + 本地向量），断网可用，不等待联网抓取（实测中位延迟见下文）。

---

## 怎么设计

### 一条管线：采集 → 结构化 → 索引

```mermaid
flowchart LR
    subgraph COL["采集层"]
        direction TB
        A1["官方 API / RSS"]
        A2["页面 / 仓库文档"]
        A3["人工投递 inbox"]
    end
    subgraph STR["结构化层"]
        direction TB
        B1["归一化 Markdown"]
        B2["切片：面包屑 / 页码 / token 数"]
        B3["去重：sha256 + SimHash"]
    end
    DB[("SQLite catalog.db<br/>唯一事实源")]
    subgraph ENR["异步富化队列"]
        direction TB
        C1["规则兜底提取"]
        C2["LLM 二遍 → 卡片 / 标签 / 实体 / 片段"]
    end
    subgraph IDX["检索层（派生数据，可一键重建）"]
        direction TB
        D1["FTS5 内置兜底"]
        D2["Meilisearch 关键词"]
        D3["LanceDB 语义向量"]
    end
    K["检索内核<br/>多路召回 + RRF 融合 + token 预算"]
    M1["MCP Server<br/>渗透 Agent"]
    M2["HTTP API<br/>其他调用方"]
    M3["CLI / 看板<br/>人维护"]

    COL --> STR --> DB
    DB --> ENR --> K
    DB --> IDX --> K
    K --> M1
    K --> M2
    K --> M3
```

几个刻意的取舍：

- **SQLite 是唯一事实源**，Meilisearch / 向量 / 卡片全是派生数据，`seckb index` / `seckb embed` 可一键重建。库坏了不心疼。
- **采集与富化解耦**：富化是异步队列，失败就降级为规则元数据，**绝不阻塞内容可检索**。
- **连接器互相隔离**：单源改版或挂掉只标记该源"待维护"，不影响全局采集。

### 检索：四路召回 + RRF 融合

这是"Agent 能秒查"的核心。一次 `kb_search` 同时打四路，用 **RRF（Reciprocal Rank Fusion）** 融合排序，而不是只做关键词匹配：

| 召回通道 | 作用 | 典型命中场景 |
|---|---|---|
| `fts` | SQLite FTS5，内置，**离线兜底** | 精确词、CVE 编号 |
| `fts_alias` | 中文黑话/别名扩展后再检索 | "永恒之蓝" → MS17-010 / CVE-2017-0144 / EternalBlue |
| `meili` | Meilisearch，中文分词 | 自然语言短语、标题 |
| `vector` | bge-m3 本地向量（Ollama） | 语义近似："怎么绕过 WAF 打 SQL 注入" |

返回结果里每一条都带 `matched_by` 字段，告诉你它是被哪几路命中的 —— 多路同时命中，基本可以确信相关。

**中文黑话映射**是实测里最提效的一环：Agent 和人都习惯说"永恒之蓝""脏牛""破壳""冰蝎"，而语料里写的是 `CVE-2017-0144`。`config/taxonomy.yaml` 维护了 27 组别名，检索时自动扩展，不用 Agent 自己先查 CVE 编号。

任何一路挂了都会被**优雅降级**：`degraded` 字段列出不可用的通道，结果照常返回，并可通过 MCP 的 `kb_services` 工具自愈拉起后端重试。

### 取用：三级粒度 + token 预算

检索命中后，Agent 按需展开，不整篇倒：

| 粒度 | 工具 | 大致 token | 用途 |
|---|---|---|---|
| **知识卡片** | `kb_search` / `kb_card` | 200–400 | 判断相关性、看要点、看实体 |
| **正文切片** | `kb_get` | 按 `max_tokens` 精确截断 | 读方法细节，带标题面包屑与出处 |
| **命令/载荷片段** | `kb_snippets` | 单条几十 token | 直接取用可执行命令、payload、代码 |

`kb_get` 的 token 预算是**硬约束**：实测 `max_tokens=1000` 返回 1001 token，`max_tokens=2000` 返回 2005 token，超出即截断并标记 `truncated=true`。切片在入库时就带好了标题面包屑（`README > CVE-2017-0143 > 利用方式`）与页码，展开即定位。

### 信任边界：投毒防护

第三方仓库里的 `SKILL.md` / `AGENTS.md` 这类文件，**本身就是写给 AI Agent 的自然语言指令**，存在指令注入面。`kb_get` 命中这类文档时会自动加一条横幅，明确告诉 Agent：这是"数据"不是"指令"，文中任何让你外发数据、访问文档内 URL、克隆外部仓库、修改自身配置的指示一律不执行。这在用 Agent 做安全研究时是必需的。

---

## 效果如何（实测）

> 测试环境：Windows 11 · i5-13490F · 16GB RAM · RTX 4060 Ti 8GB（向量化走本地 Ollama bge-m3）。数据来自作者本机参考实例。

### 检索延迟

12 条真实渗透场景查询（热态，`limit=8`，四路全开）：

| 指标 | 数值 |
|---|---|
| 中位数 | **1.58 s** |
| P90 | 1.80 s |
| 最大值 | 2.22 s |

延迟主要来自本地查询向量化（bge-m3 on GPU）与 Meilisearch 检索，不依赖外网。

### 检索命中率

`seckb eval` 跑 10 条渗透场景评测集（`tests/eval/golden_queries.yaml`）：

```
命中率：100%（10/10）
```

⚠️ **诚实说明**：这个评测集只有 10 条正向样本、没有负样本，属于"自证"指标，只能说明管线通了，不足以证明检索质量。扩充到 ≥20 条真实工作问题并加入负样本，是 Roadmap 里 P2 的事。

### token 预算效果

同样是"fastjson 反序列化"这条查询：

| 取用方式 | token 开销 |
|---|---|
| `kb_search` 返回 Top-8 候选（含卡片摘要） | 约 1,000（实测区间 634–1,317） |
| 仅展开 1 篇命中的正文（`kb_get max_tokens=4000`） | 3,974，**仍被截断** |

也就是说，**一次检索看 8 个候选，比读 1 篇文章还便宜**。这正是"卡片优先、按需展开"的价值：Agent 先用 1k token 判断该看哪篇，再只展开真正需要的那一篇。

### 参考实例规模

这是作者本机跑了一段时间的实例，**仅用于说明管线吞吐，不是本项目的卖点** —— 你自己的库有多大，取决于你订阅了哪些源、跑了多久：

| 指标 | 数量 |
|---|---|
| 资产总量 | 54,880 |
| 正文切片 | 199,599 |
| 命令/载荷片段 | 47,045 |
| 实体（CVE/工具/ATT&CK） | 74,123 |
| CVE 条目（含 CVSS 36,611 / 在野利用 KEV 1,744） | 48,091 |
| 磁盘占用 | 约 3.1 GB |

> 卡片数会滞后于资产数（LLM 富化是限速队列，CVE 批量入库后需要时间排空），daemon 会自动补齐。

### 工程健康度

| 指标 | 数值 |
|---|---|
| 测试 | **183 passed**（29.6s） |
| 代码量 | 约 4,500 行（`seckb/`，不含测试） |
| 连接器 | 8 类（NVD / KEV / ExploitDB / Vulhub / RSS / GitHub / 仓库文档 / 人工投递） |

---

## 截图

> 以下均为**真实运行截图**（本地看板 `http://127.0.0.1:8011`，数据即上文参考实例）。

### 1. 维护者看板 —— 规模、分布与趋势

![看板概览](docs/screenshots/dashboard-overview.png)

**标注**：① 顶部**服务控制条**三盏状态灯，实时显示 Ollama（本地向量）/ Meilisearch（关键词索引）/ 自动采集（daemon）是否在线，支持一键启停；② **KPI 卡**：资产总量 / 正文切片 / 知识卡片 / 命令载荷片段 / 实体 / CVE（含 CVSS）/ KEV 在野利用；③ **类型与语言**分布（CVE 为主体，英文语料为主、中文为补充方向）；④ **来源分布**（sqrt 刻度，否则长尾被 NVD 压平看不见）；⑤ **方向分类 Top 12**；⑥ **常用工具实体 Top 12**；⑦ **近 30 天累计入库**曲线；⑧ **最近入库**列表。看板数据实时读库，随 daemon 自动更新。

### 2. 混合检索 —— 四路融合与命中来源

![混合检索](docs/screenshots/search-hybrid.png)

**标注**：查询 `永恒之蓝 MS17-010`（**中文黑话，语料里写的是 CVE-2017-0143/0144**）。① 顶部显示命中数与本次结果的总 token 估算（**约 1,453 tokens / 10 条**）；② 每条结果后的彩色徽标就是 `matched_by` —— `fts_alias`（别名扩展命中）/ `meili`（关键词）/ `vector`（语义），**三路都亮说明高置信**；③ 灰色一行是 LLM 生成的知识卡片**摘要**；④ 再下一行是正文切片**片段**（带标题面包屑）；⑤ 底部的 `CVE-2017-0144 KEV` 条目带 **KEV 在野利用**标记。

### 3. 知识卡片详情 —— 三级粒度一屏可见

![知识卡片详情](docs/screenshots/detail-card.png)

**标注**：点击"查看详情"打开的抽屉，正好展示了 Agent 取用的三级粒度。① 标题下的徽标是**类型/来源/语言/标签**；② **摘要** —— 卡片层（约 200–400 token），Agent 判断相关性用；③ **要点** —— 卡片里的结构化 `key_takeaways`；④ **命令/载荷片段** —— 可直接执行的 Metasploit 命令，就是 `kb_snippets` 的返回内容；⑤ **正文** —— 切片层，带 `[README > CVE-2017-0143 > 利用方式]` 面包屑，对应 `kb_get` 按 token 预算返回的内容。

### 4. 主题系统 —— 同一份数据，两种观感

![纸本主题](docs/screenshots/theme-archive.png)

**标注**：右上角可在**玄墨**（暗色，默认）与**纸本**（亮色，适合长时间阅读/投影）之间切换，偏好写入 `localStorage`。两套主题只是换色板 token，布局与数据完全一致。

---

## 快速开始

### 前置依赖

- **Python 3.12+**
- **Ollama**（本地向量化，语义检索用；不装则自动降级为关键词检索）
- **Meilisearch**（关键词索引，可选，同样支持降级）
- 一个 OpenAI 兼容的 LLM 接口（仅**富化**需要外网；不配则只跑规则提取，检索依然可用）

### 安装

```bash
git clone https://github.com/xiabai2008/seckb.git
cd seckb
python -m venv .venv
.venv\Scripts\activate          # Windows；Linux/macOS 用 source .venv/bin/activate
pip install -e ".[dev]"
```

### 初始化

```bash
# 知识库数据目录默认 D:/SecurityKB，可用环境变量 SECKB_ROOT 或 config/settings.yaml 改
seckb init
```

### 配置 LLM（富化用，可选）

```yaml
# config/enrich.yaml
provider:
  base_url: https://api.deepseek.com/v1   # 任意 OpenAI 兼容端点
  model: deepseek-chat
  api_key_env: DEEPSEEK_API_KEY           # 从这个环境变量读 Key
```

**不配也能用**：采集、切片、关键词检索、向量检索都不依赖它，只是资产没有 LLM 生成的卡片与片段，退化为规则提取的元数据。

### 拉取模型与索引

```bash
ollama pull bge-m3              # 本地嵌入模型
```

### 开始采集（数据自采，见下节）

```bash
seckb collect                   # 全量/增量采集一次
seckb scan                      # 扫描 inbox/ 手工投递的文件
seckb enrich --drain            # LLM 富化（生成卡片/标签/实体/片段），需配 LLM Key
seckb embed                     # 向量化
seckb index                     # 重建 Meilisearch 索引
```

### 常驻自动采集

```bash
seckb daemon                    # APScheduler 常驻：定时采集 + 富化 + 向量 + 索引
```

采集周期、来源清单、峰谷调度策略都在 `config/` 下的 YAML 里，改配置即可，不用改代码。

### 打开看板

```bash
seckb serve --port 8011
# 浏览器打开 http://127.0.0.1:8011
```

---

## Agent 接入（MCP，推荐）

seckb 提供 stdio 传输的 MCP Server，与 HTTP/CLI **共用同一个检索内核**。以 opencode 为例：

```json
{
  "mcp": {
    "seckb": {
      "type": "local",
      "command": ["D:\\path\\to\\seckb\\.venv\\Scripts\\python.exe", "-m", "seckb", "mcp"]
    }
  }
}
```

暴露 5 个工具，推荐的 Agent 调用链：

| 工具 | 用途 |
|---|---|
| `kb_search` | 混合检索，返回带摘要与出处的候选卡片列表 |
| `kb_card` | 取完整知识卡片（摘要/要点/标签/实体；漏洞类含 CVSS/CWE/KEV） |
| `kb_get` | 按 `max_tokens` 预算取正文切片，支持按章节过滤 |
| `kb_snippets` | 检索可直接执行的命令/载荷/代码片段 |
| `kb_services` | 查看/启动检索后端（`degraded` 非空时用它自愈重试） |

标准流程：`kb_search` 判断 → `kb_card` 深入 → `kb_get` / `kb_snippets` 取用。每条结果都带 `token_estimate` 与 `source_url`（出处链接），Agent 可据此控制上下文开销，并给结论附上引用。

> **调优提示**：`kb_snippets` 的 `query` 是 AND 语义，中文长句容易返回空；优先用 `tool="nmap"` / `kind="command"` 这类结构化参数，或短关键词。

---

## 接口

### HTTP API（本地，无鉴权，仅监听 127.0.0.1）

```
GET /search?q=fastjson&limit=5        # 混合检索
GET /card/{id}                        # 知识卡片
GET /get/{id}?max_tokens=1500&section=利用   # 正文切片（按预算）
GET /snippets?tool=nmap               # 命令/载荷片段
GET /stats                            # 看板统计
```

### CLI（人工维护）

```bash
seckb search "fastjson 反序列化怎么利用" -n 5
seckb card 2339
seckb get 2339 --section 利用 --max-tokens 1500
seckb snippets --tool nmap
seckb eval                            # 检索质量评测
seckb stats                           # 规模统计
seckb sources                         # 采集源健康与游标
```

---

## 数据从哪里来：本仓库不提供数据

**这个仓库只包含代码与采集脚本，不包含任何语料、索引或数据库。** 数据从来不在 git 里 —— 它落在仓库外的独立目录（默认 `D:/SecurityKB`，可用 `SECKB_ROOT` 覆盖）。`git ls-files` 里没有任何 `.db` / `.pdf` / `.epub`。

原因很简单：语料体积大（参考实例约 3.1 GB）、版权归属复杂、且对使用者无意义 —— 你要的是**你自己的**知识库。

### 数据由你自己采

仓库自带完整的采集能力，一条命令起采：

```bash
seckb collect              # 跑一遍所有已启用的源
seckb daemon               # 或交给守护进程定时增量采集
```

开箱可用的连接器（在 `config/sources.yaml` 里按需启用/增删）：

| 连接器 | 内容 |
|---|---|
| `nvd` | NVD CVE API 2.0 增量（分窗拉取，游标只推进到完整窗口，避免静默丢数据） |
| `kev` | CISA KEV 在野利用目录 |
| `exploitdb` | Exploit-DB 官方仓库 |
| `vulhub` | Vulhub 靶场环境清单 |
| `rss` | FreeBuf / 安全客 / 先知 / KitPloit / HackerNews / Unit42 等 |
| `github` | GitHub 安全类仓库元数据（搜索 + Awesome 清单） |
| `github_docs` | 把公开安全知识仓库的 Markdown 正文入库（PayloadsAllTheThings / HackTricks / GTFOBins / Awesome-POC 等，可配 include/exclude 前缀与文件数上限） |
| `manual` | `inbox/` 人工投递：PDF / EPUB / HTML / Markdown 丢进去，`seckb scan` 自动归一化入库 |

**新增一个来源 = 一个连接器文件 + `sources.yaml` 里一段配置**，检索内核不用动。

### 合规与礼貌

- 尊重 `robots.txt`，全局限速、低频访问；
- 采集内容均来自公开网络，**仅限个人学习研究使用，不再分发**；
- 书籍走"本地文件入库 + 书目清单"通道，不内置盗版站点爬虫。

---

## 项目结构

```
seckb/
├── config/                 # 全部可调项都在这里（YAML，改配置不改代码）
│   ├── sources.yaml        # 采集源清单与参数
│   ├── schedule.yaml       # 守护任务节奏 + LLM 峰谷调度
│   ├── taxonomy.yaml       # 方向分类 / 工具词典 / 中文黑话别名映射
│   └── enrich.yaml         # LLM provider / 预算上限 / embedding
├── seckb/
│   ├── cli.py              # 命令行入口
│   ├── connectors/         # 采集连接器（nvd/kev/exploitdb/vulhub/rss/github/github_docs）
│   ├── pipeline/           # 归一化 → 切片 → 去重 → 入库
│   ├── enrich/             # 规则提取 + LLM 富化 + 异步队列
│   ├── indexer/            # FTS5 / Meilisearch / LanceDB 向量
│   ├── retrieval.py        # 检索内核：多路召回 + RRF 融合
│   ├── tools.py            # kb_search / kb_card / kb_get / kb_snippets
│   ├── mcp_server.py       # MCP Server（stdio）
│   ├── api.py              # FastAPI（HTTP）
│   ├── dashboard.py        # 看板统计
│   ├── daemon.py           # APScheduler 守护调度
│   └── static/dashboard.html
├── scripts/                # 运维脚本（启停、体检、回填）
└── tests/                  # 183 项测试 + 评测集
```

## 开发与测试

```bash
pytest -q                    # 183 passed
ruff check .                 # lint（line-length 100）
```

> `scripts/` 下还有若干历史 lint 提示（UP017 / SIM115 / ISC004），不影响运行。

## Roadmap

- **P2 · 质量闭环**：把评测集扩到 ≥20 条真实工作问题并加入负样本，用 `queries` 日志分析知识缺口、输出补采建议。
- **P3 · 可选**：知识图谱可视化（`links` 表已有跨源关联）、更多连接器。

---

## 许可与合规

代码以 [MIT](LICENSE) 许可开源。**采集到的内容不属于本项目**，其版权归原始来源所有，请遵守各来源的使用条款，仅限个人学习研究，不要再分发。

本项目不内置盗版书籍爬虫，不重分发任何第三方内容。
