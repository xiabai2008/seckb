# 网络安全本地知识库（seckb）设计文档 — AI 优先版

- 日期：2026-09-13
- 状态：已评审（AI 优先版，待实施计划）
- 部署环境：单机 Windows 11，i5-13490F / 16GB RAM / RTX 4060 Ti 8GB，Docker/Python 3.12/Node 24 可用
- 代码位置：`D:\HZR_PROJECTS\seckb`（git 管理）
- 数据位置：`D:\SecurityKB`（不开 git，由 SQLite 编目）

## 1. 背景与目标

为自研渗透测试 agent 建设的本地网络安全知识库。**第一消费对象是 AI agent，人是维护者**。agent 在工作时（信息收集、漏洞利用、绕过、横向）通过 MCP / HTTP 接口实时检索知识库，获得可信、带出处的知识储备，提高工作效率。

内容覆盖六大板块：安全电子书、社区帖子/博客、GitHub 资源索引、漏洞库与威胁情报、CTF/Writeup、标准/合规文档。

核心目标：

1. 越大越全：可持续滚雪球式采集，数据量增长不失控
2. **Agent 可消费**：一切内容以 Markdown 文本 + 结构化元数据存在，切片、卡片、片段三级粒度供 agent 按 token 预算取用
3. **语义可检索**：混合检索（关键词 + 向量），"怎么绕过 WAF 打 SQL 注入"这类问题能命中
4. 一条命令完成全量/增量更新，自动定时运行
5. 断网可用：检索核心（SQLite + FTS5 + 本地向量）完全本地；仅富化需要外网
6. 数据自有、可迁移、可备份

## 2. 非目标

- 不做多用户 / 在线服务，仅单机个人使用
- 不做独立 RAG 问答：agent 自身就是 LLM，知识库只负责"高质量零售检索"，不做中间商
- 不内置盗版书籍站点爬虫；书籍以本地文件入库 + 书目缺口清单 + 合法公开源为主
- 不整仓 clone GitHub 仓库，只索引元数据（重要仓库可人工选择 mirror）
- 不重分发任何内容，仅个人学习自用

## 3. 总体架构

```
                 ┌──────────────────── 采集层 ────────────────────┐
 API/RSS源 ──►┐  │                                                │
 页面爬虫  ──►├──┤ 连接器(connectors) ──► 归一化MD ──► 切块 ──► 去重 ─┤─► SQLite(事实源)
 人工投递  ──►┘  │                                                │   ├─► Meilisearch(FTS索引)
                 └──────────────┬─────────────────────────────────┘   ├─► LanceDB(向量索引)
                                │                                     └─► 文件区(原件+MD)
                     富化队列(异步) ──► 规则提取 + 云端LLM ──► 卡片/标签/实体/片段
                                │
                 ┌──────────────▼──────────────┐
                 │  检索内核 (融合排序/权限/预算) │
                 └───────┬──────────────┬──────┘
                         │              │
                  MCP Server        HTTP API        CLI(人工维护)
                  (渗透agent)        (其他调用方)
```

关键约束：

- SQLite 是唯一事实源；Meilisearch / LanceDB / 卡片都是派生数据，可一键重建
- 每个连接器独立实现、互相隔离，单源故障不影响全局
- 富化是异步队列，采集与富化解耦；富化失败不阻塞内容可检索（降级为规则元数据）

## 4. 数据仓库目录结构（D:\SecurityKB）

```
D:\SecurityKB\
├── inbox\               # 人工投递区：文件丢进来即自动入库、归档
├── books\<方向>\        # 电子书原件（PDF/EPUB + .meta.json），方向用英文 slug
│                        #   web-security\ pentest\ reverse-engineering\ crypto\
│                        #   code-audit\ cloud-security\ ics-security\ mobile-security\
│                        #   incident-response\ data-security\ ...
├── posts\zh\ posts\en\  # 帖子归一化 Markdown，图片本地化存储
├── repos\               # GitHub 资源索引 JSON（可选 mirror\ 放重要仓库镜像）
├── vulndb\              # CVE/Exploit-DB/Vulhub 数据，按年份分片
├── ctf\                 # CTF Writeup 与靶场笔记
├── standards\           # OWASP/NIST/等保/ISO 等文档
└── meta\
    ├── catalog.db       # SQLite 事实源
    ├── lancedb\         # 向量库
    ├── wanted.yaml      # 书目缺口清单
    ├── logs\            # 采集/富化运行日志
    └── snapshots\       # 索引快照
```

命名约定：目录名用英文（规避工具兼容问题）；分类名与标签在 DB 中用中文。

## 5. 数据模型（SQLite）

| 表 | 作用 | 关键字段 |
|---|---|---|
| `assets` | 一切内容总表 | id, type(book/post/repo/cve/writeup/standard), title, lang, source, source_url, path, md_path, sha256, size, format, published_at, imported_at, tags(JSON), category, status |
| `chunks` | 正文切片（agent 展开单元） | id, asset_id, seq, heading_path, page_from, page_to, token_count, content_md |
| `snippets` | 命令/载荷/代码片段 | id, asset_id, chunk_id, kind(command/payload/oneliner/code), lang, tool, content, context |
| `entities` | 实体字典 | id, kind(cve/tool/attack/owasp/product/actor), name, canonical |
| `asset_entities` | 资产-实体关联 | asset_id, entity_id, weight |
| `cards` | 知识卡片（agent 第一入口） | asset_id, summary, key_takeaways(JSON), card_json, model, generated_at |
| `books / posts / repos / cves` | 各类型扩展表 | ISBN/作者/出版社；站点/作者/板块；stars/topics/license；CVSS/CWE/KEV |
| `sources` | 连接器游标 | name, last_cursor, last_run_at, etag, enabled, health |
| `jobs` | 富化异步队列 | id, asset_id, kind(summary/embed/extract), status, attempts, last_error |
| `queries` | agent 查询日志 | query, filters, results, latency, ts（P2 用于缺口分析） |
| `links` | 跨源关联 | src_asset_id, dst_asset_id, relation |
| `runs` | 采集运行日志 | source, started_at, fetched, imported, skipped, failed, error |

去重策略：`assets.sha256` 精确去重 + 帖子 SimHash 近似去重 + URL 规范化；书籍叠加 ISBN/标题模糊匹配。

## 6. 内容处理管线（AI 优先的核心）

### 6.1 格式归一化

- 帖子/网页：正文抽取 → 标准 Markdown，图片下载到 `assets/<id>/` 并改写链接
- PDF/EPUB：PyMuPDF4LLM 转 Markdown；扫描件走 OCR（RapidOCR）兜底；原件始终保留
- GitHub 仓库：README 转 Markdown 作为正文，元数据进 `repos`
- 所有内容在 `assets.md_path` 指向规范 Markdown，检索永不直接读 PDF

### 6.2 切块（chunking）

- 按标题层级切：目标 500~1000 token/块，块间 10~15% 重叠
- 每块带面包屑（`文档标题 > H2 > H3`）、页码（PDF）、token 数
- 切块在入库时完成，chunk 是向量化、片段抽取、检索的最小单元

### 6.3 富化（异步队列）

1. **规则先扫**：正则/词典提取 CVE 编号、工具名（nuclei/sqlmap/…）、ATT&CK 技术号、命令与载荷模式 → 立即可用的兜底元数据
2. **云端 LLM 二遍**：OpenAI 兼容接口（默认 DeepSeek，可切 Qwen 等），对每个资产输出结构化 JSON：
   - `summary` + `key_takeaways[]`（组成知识卡片）
   - `tags[]`、`entities`（CVE/工具/ATT&CK/OWASP/产品）
   - `snippets[]`（kind/lang/tool/content/context）
3. **队列控制**：`jobs` 表驱动，限流、重试、预算上限（token/费用）可配；提示词与输出 schema 版本化，支持批量重跑
4. **向量化**：本地 bge-m3（Ollama，RTX 4060 Ti GPU 加速），对 chunk 生成 embedding 写入 LanceDB；富化失败不阻塞向量可用

### 6.4 知识卡片

每个资产一张 200~400 token 的紧凑卡片（`cards.card_json`）：摘要、要点、标签、实体、来源与日期、可信度。**Agent 检索默认先拿卡片判断相关性，再按需展开 chunk 或取 snippet**，节省上下文。

## 7. 采集策略

### 7.1 连接器分三级

**T1 官方 API / RSS（无人值守，第一批实现）**

- GitHub：API 拉取安全类仓库元数据、解析 Awesome 系列清单、trending 快照
- 漏洞：NVD CVE API 2.0（增量）、CISA KEV 目录、Exploit-DB 官方 git 仓库、Vulhub 环境清单
- 社区 API：HackerNews、Reddit r/netsec 等、CTFtime
- RSS：FreeBuf、安全客、看雪、The Hacker News、BleepingComputer、KitPloit

**T2 页面解析（需登录/反爬，礼貌低频，第二批实现）**

- 先知社区、看雪论坛、吾爱破解、知乎/掘金安全话题
- Playwright + 手动登录 cookies（约每月更新一次），限速 1 请求 / 3~5 秒
- 页面结构变化时仅标记该连接器"待维护"，不中断全局采集

**T3 人工投递（兜底，第一天可用）**

- `inbox` 目录监控：新文件 → 元数据提取 → 去重 → 入库 → 归档
- 浏览器保存的 .html/.mhtml 自动转 Markdown 入库
- 书籍通道：用户自行提供文件；`meta/wanted.yaml` 维护书目清单，每周生成缺口报告

### 7.2 书籍处理

- PyMuPDF 提取书名/作者/页数/封面，识别 ISBN
- 关键词规则自动归入方向目录；云端 LLM 富化时精修标签
- 以本地文件入库为主，附加合法公开源（出版社免费章节、Springer Open 等）自动抓取

### 7.3 增量与调度

- 每个连接器独立周期（`config/schedule.yaml`）：NVD 每日、RSS 每 6 小时、GitHub 每周、论坛每日限速
- 常驻守护进程 `seckb daemon`（APScheduler），开机自启；支持 `seckb collect --source <name>` 手动触发
- 断点续采（`sources` 表游标/ETag），幂等入库（sha256 命中跳过），失败进重试队列

### 7.4 合规与礼貌

- 尊重 robots.txt，全局限速，低频访问
- 内容仅个人学习自用，不做任何形式再分发

### 7.5 第一周冲刺顺序

1. GitHub 索引 + NVD/Exploit-DB/Vulhub 元数据
2. 中英文 RSS 帖子
3. 先知/看雪深水区（需登录）
4. 书籍清单驱动补齐

## 8. 检索与 Agent 接口

### 8.1 混合检索

- 关键词：Meilisearch（中文 charabia 分词，无需 IK）
- 语义：本地 bge-m3 embedding + LanceDB 向量检索
- 融合：RRF（Reciprocal Rank Fusion）合并两路结果，支持按 type/tag/lang/年份/可信度过滤
- 离线兜底：SQLite FTS5（Meilisearch/向量未启动时仍可关键词检索）

### 8.2 MCP Server（渗透 agent 主通道）

工具集（stdio 传输，与 HTTP 同一检索内核）：

| 工具 | 用途 | 关键参数 |
|---|---|---|
| `kb_search` | 混合检索，返回命中卡片摘要 | query, type?, tags?, limit, max_tokens |
| `kb_card` | 取完整知识卡片 | asset_id |
| `kb_get` | 取正文切片（按 token 预算截断，带面包屑/出处） | asset_id, section?, max_tokens |
| `kb_snippets` | 按工具/类型检索命令、载荷、代码片段 | query?, tool?, kind?, limit |

响应统一 JSON：`{results: [...], token_estimate, citations: [{asset_id, title, path, source_url, date, confidence}]}`。

### 8.3 HTTP API

- FastAPI，与 MCP 共用检索内核，端点一一对应（`/search`、`/card/{id}`、`/get/{id}`、`/snippets`）
- 供未来其它语言调用方使用；本地监听，无鉴权（仅 127.0.0.1）

### 8.4 CLI（人工维护）

- `seckb search ...`、`seckb open <id>`（打开原件）、`seckb stats`、`seckb collect`、`seckb enrich`、`seckb eval`

## 9. 工程结构

```
seckb/
├── pyproject.toml
├── config/
│   ├── sources.yaml      # 来源清单
│   ├── schedule.yaml     # 采集周期
│   ├── taxonomy.yaml     # 方向/标签/实体词典（CVE 正则、工具表、ATT&CK 映射）
│   └── enrich.yaml       # LLM provider、预算上限、提示词版本
├── seckb/
│   ├── cli.py            # 入口命令
│   ├── db.py             # schema 与迁移
│   ├── models.py         # Asset/Chunk/Snippet/Card 等模型
│   ├── connectors/       # github.py nvd.py rss.py xianzhi.py ...
│   ├── pipeline/         # normalize.py chunker.py dedupe.py archive.py
│   ├── enrich/           # rules.py llm.py queue.py cards.py
│   ├── indexer/          # meili.py vectors.py fts.py fusion.py
│   ├── api/              # mcp_server.py http_api.py（共用 search core）
│   ├── daemon.py         # APScheduler 常驻调度
│   └── eval/             # 评测脚本与打分
└── tests/
    ├── eval/golden_queries.yaml   # 渗透场景评测集
    └── fixtures/                  # 连接器录制的 HTML/JSON
```

核心约束：连接器统一接口 `fetch(cursor) -> items`；新增来源 = 一个连接器文件 + 一行 YAML；检索内核唯一，MCP/HTTP/CLI 都调用它。

## 10. Roadmap

- **P1 地基 + Agent 接口**：骨架 → inbox 导入 → 归一化/切块 → T1 连接器 → 富化队列（规则+云端 LLM）→ 混合检索 → MCP + HTTP 双接口 → daemon 定时。
  完成标志：渗透 agent 能通过 MCP 问"fastjson 反序列化怎么打"，拿到带出处的卡片/片段；搜"永恒之蓝 / HTB"秒出结果
- **P2 质量闭环**：`tests/eval/golden_queries.yaml` 渗透场景评测集（≥20 条真实工作问题）量化命中率；`queries` 日志分析知识缺口，输出补采建议
- **P3 可选**：Web 门户（人维护用：浏览/标签/统计）+ 知识图谱可视化（links 表）
- P2/P3 各自单独立项；P1 只交付地基与 agent 接口

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| 论坛反爬 / 登录失效 | 低频 + inbox 人工兜底；连接器互相隔离 |
| 来源改版导致连接器腐化 | fixtures 回归测试 + 健康报告定位故障源 |
| LLM 富化出错/成本失控 | 规则兜底 + 队列限流/重试 + 预算上限 + schema 版本化可重跑 |
| 向量库/索引损坏 | 一切为派生数据，`seckb index rebuild` 一键重建 |
| 磁盘膨胀 | 默认 300GB 预警线（可配）；GitHub 只存索引不 clone |
| 版权 | 仅个人学习自用，不重分发；书籍以本地入库为主 |
| 维护成本 | 配置 YAML 化；单源故障不影响全局 |

## 12. 关键决策记录

| 决策点 | 结论 | 理由 |
|---|---|---|
| 知识库定位 | AI agent 第一消费对象，人只做维护 | 服务于自研渗透 agent 的实际工作检索 |
| 总体路线 | 分阶段：先地基后门面 | 快速可用，架构不返工 |
| 架构模式 | 统一资产管道（方案 A） | 单机场景兼顾增量、跨源关联与 agent 检索 |
| 检索栈 | Python + SQLite + Meilisearch + LanceDB | 16GB 内存下轻量；中文友好；本地向量免费 |
| Agent 接口 | MCP + HTTP 双接口，共用一个检索内核 | 兼容任意 agent 工具链，避免重复实现 |
| 内容粒度 | 卡片 / chunk / snippet 三级 | agent 按 token 预算取用，省上下文 |
| 富化方式 | 规则兜底 + 云端 LLM（OpenAI 兼容，默认 DeepSeek） | 质量换成本可控；接口可切换到任意 provider |
| 向量化 | 本地 bge-m3（Ollama，RTX 4060 Ti） | 免费、快、隐私好；免装 2.5GB torch；可切云端 embedding |
| 采集节奏 | 自动定时增量 | 长期滚雪球 |
| 语言策略 | 中文优先、英文并重 | 中文源解析规则先做，英文源按需增量 |
| 书籍通道 | 本地文件入库 + 书目清单 + 合法公开源 | 规避盗版爬虫风险，工具只管入库编目 |
| RAG 问答 | 不做 | agent 自身就是 LLM，知识库只做零售检索 |

## 13. 成功标准

1. 渗透 agent 通过 MCP 完成"提问 → 卡片判断 → 展开 chunk/片段"的标准检索流程，全程 < 2s
2. 任意关键词/语义查询中文检索 < 1s，覆盖书籍 / 帖子 / 漏洞 / 仓库 / 片段
3. 混合检索在 P2 评测集上命中率 ≥ 80%（Top-5 含相关资产）
4. 一条命令完成全量 / 增量更新；断网时关键词与向量检索仍可用
5. 数据完全本地自有，可迁移、可备份
