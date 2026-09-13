# 网络安全本地知识库（seckb）设计文档

- 日期：2026-09-13
- 状态：已评审（待实施计划）
- 部署环境：单机 Windows 11，i5-13490F / 16GB RAM / RTX 4060 Ti 8GB，Docker/Python 3.12/Node 24 可用
- 代码位置：`D:\HZR_PROJECTS\seckb`（git 管理）
- 数据位置：`D:\SecurityKB`（不开 git，由 SQLite 编目）

## 1. 背景与目标

从零搭建一个本地网络安全知识库，内容覆盖安全电子书、社区帖子/博客、GitHub 资源索引、漏洞库与威胁情报、CTF/Writeup、标准/合规文档六大板块，并预留 AI 问答与 agent 接口。

核心目标：

1. 越大越全：可持续滚雪球式采集，不因数据量增长而失控
2. 一条命令完成全量/增量更新，自动定时运行
3. 任意关键词中文全文检索 < 1 秒
4. 断网可用：核心数据（文件 + SQLite + FTS5）完全本地
5. 数据自有、可迁移、可备份、可被 AI agent 查询（P3）
6. 中文优先、英文并重

## 2. 非目标

- 不做多用户 / 在线服务，仅单机个人使用
- P1 不做 Web UI 与 AI 问答（属于 P2 / P3）
- 不内置盗版书籍站点爬虫；书籍以本地文件入库 + 书目缺口清单 + 合法公开源为主
- 不整仓 clone GitHub 仓库，只索引元数据（重要仓库可人工选择 mirror）
- 不重分发任何内容，仅个人学习自用

## 3. 总体架构（方案 A：统一资产管道）

所有内容抽象为统一的“资产(Asset)”，走同一条流水线：

```
                    ┌─────────────── 采集层 ───────────────┐
  API/RSS源 ──►┐                                          │
  页面爬虫  ──►├─► 连接器(connectors) ──► 归一化 ──► 去重 ──┼─► SQLite(事实源)
  人工投递  ──►┘        │                                 │   └─► Meilisearch(派生索引)
                    原始快照                              │
                                                        └─► 文件区(人可读/人可翻)

  P2: Web门户(FastAPI)        P3: 本地向量库 + RAG 问答 + MCP 接口
```

关键约束：

- SQLite 是唯一事实源；Meilisearch 是派生索引，可随时全量重建
- 每个连接器独立实现，互相隔离，单个来源故障不影响全局
- 代码与数据分离：代码进 git，数据靠 DB 编目与备份

## 4. 数据仓库目录结构（D:\SecurityKB）

```
D:\SecurityKB\
├── inbox\               # 人工投递区：文件丢进来即自动入库、归档
├── books\<方向>\        # 电子书（PDF/EPUB + .meta.json），方向用英文 slug
│                        #   web-security\ pentest\ reverse-engineering\ crypto\
│                        #   code-audit\ cloud-security\ ics-security\ mobile-security\
│                        #   incident-response\ data-security\ ...
├── posts\zh\ posts\en\  # 帖子统一转 Markdown，图片本地化存储
├── repos\               # GitHub 资源索引 JSON（可选 mirror\ 放重要仓库镜像）
├── vulndb\              # CVE/Exploit-DB/Vulhub 数据，按年份分片
├── ctf\                 # CTF Writeup 与靶场笔记
├── standards\           # OWASP/NIST/等保/ISO 等文档
└── meta\                # catalog.db、wanted.yaml、采集日志、索引快照
```

命名约定：目录名用英文（规避个别工具对中文路径的兼容问题），分类名与标签在 DB 中用中文。

## 5. 数据模型（SQLite）

| 表 | 作用 | 关键字段 |
|---|---|---|
| `assets` | 一切内容的总表 | id, type(book/post/repo/cve/writeup/standard), title, lang, source, source_url, path, sha256, size, format, published_at, imported_at, tags(JSON), category, status |
| `books` | 书籍扩展表 | asset_id, isbn, authors, publisher, year, pages, edition, cover_path, reading_status |
| `posts` | 帖子扩展表 | asset_id, site, author, board, views, replies, original_html_path |
| `repos` | 仓库扩展表 | asset_id, owner, name, stars, forks, language, topics, clone_url, license, archived, last_commit |
| `cves` | 漏洞扩展表 | asset_id, cve_id, cvss, cwe, affected, poc_refs, in_kev |
| `sources` | 连接器游标 | name, last_cursor, last_run_at, etag, enabled, health |
| `links` | 跨源关联 | src_asset_id, dst_asset_id, relation(book→tool / post→cve / …) |
| `runs` | 采集运行日志 | source, started_at, finished_at, fetched, imported, skipped, failed, error |

去重策略：

- 精确去重：`assets.sha256` 唯一索引
- 近似去重：帖子用 SimHash（标题 + 正文），阈值可配
- URL 规范化：去除跟踪参数后比较
- 书籍叠加 ISBN / 标题模糊匹配

## 6. 采集策略

### 6.1 连接器分三级

**T1 官方 API / RSS（无人值守，第一批实现）**

- GitHub：API 拉取安全类仓库元数据、解析 Awesome 系列清单、trending 快照
- 漏洞：NVD CVE API 2.0（增量）、CISA KEV 目录、Exploit-DB 官方 git 仓库、Vulhub 环境清单
- 社区 API：HackerNews、Reddit r/netsec 等、CTFtime
- RSS：FreeBuf、安全客、看雪、The Hacker News、BleepingComputer、KitPloit

**T2 页面解析（需登录/反爬，礼貌低频，第二批实现）**

- 先知社区、看雪论坛、吾爱破解、知乎/掘金安全话题
- Playwright + 手动登录 cookies（约每月更新一次），限速 1 请求 / 3~5 秒
- 页面结构变化时仅标记该连接器“待维护”，不中断全局采集

**T3 人工投递（兜底，第一天可用）**

- `inbox` 目录监控：新文件 → 元数据提取 → 去重 → 入库 → 归档到对应目录
- 浏览器保存的 .html/.mhtml 自动转 Markdown 入库
- 书籍通道：用户自行提供文件；`meta/wanted.yaml` 维护书目清单，每周生成缺口报告

### 6.2 书籍处理

- PyMuPDF 提取书名/作者/页数/封面，识别 ISBN
- 关键词规则自动归入方向目录；后续可接本地 LLM 精修标签
- 以本地文件入库为主，附加合法公开源（出版社免费章节、Springer Open 等）自动抓取

### 6.3 增量与调度

- 每个连接器独立周期，配置在 `config/schedule.yaml`：NVD 每日、RSS 每 6 小时、GitHub 每周、论坛每日限速
- 常驻守护进程 `seckb daemon`（APScheduler），开机自启；也支持 `seckb collect --source <name>` 手动触发
- 断点续采：`sources` 表存游标 / ETag / last_run_at
- 幂等入库：sha256 命中直接跳过，失败进重试队列

### 6.4 合规与礼貌

- 尊重 robots.txt，全局限速，低频访问
- 内容仅个人学习自用，不做任何形式的再分发

### 6.5 第一周冲刺顺序

1. GitHub 索引 + NVD/Exploit-DB/Vulhub 元数据（快、量大）
2. 中英文 RSS 帖子
3. 先知/看雪深水区（需登录）
4. 书籍清单驱动补齐

## 7. 检索

- Meilisearch 主索引 `assets` + 独立漏洞库索引（数据量大，分开维护）；中文由 charabia 自动分词，无需 IK
- SQLite FTS5 离线兜底：Meilisearch 未启动时仍可搜索基本盘
- CLI 示例：
  - `seckb search fastjson --type post --tag 反序列化`
  - `seckb open <id>` 直接打开 PDF
  - `seckb stats` 查看全库构成

## 8. 工程结构

```
seckb/
├── pyproject.toml
├── config/
│   ├── sources.yaml      # 来源清单
│   ├── schedule.yaml     # 采集周期
│   └── taxonomy.yaml     # 方向与标签词表（全库分类一致性）
├── seckb/
│   ├── cli.py            # 入口命令
│   ├── db.py             # schema 与迁移
│   ├── models.py         # Asset 等数据模型
│   ├── connectors/       # github.py nvd.py rss.py xianzhi.py ...
│   ├── pipeline/         # 归一化、去重、自动打标、归档
│   ├── indexer/          # meilisearch.py fts.py
│   └── daemon.py         # APScheduler 常驻调度
└── tests/                # 连接器用录制的 HTML/JSON fixtures 做回归测试
```

核心约束：所有连接器实现统一接口 `fetch(cursor) -> items`；新增来源 = 新增一个连接器文件 + 一行 YAML 配置。

## 9. Roadmap

- **P1 地基**：项目骨架 → inbox 导入 → T1 连接器 → Meilisearch + CLI → daemon 定时。完成标志：搜“永恒之蓝 / fastjson / HTB”均秒出结果
- **P2 门户**：FastAPI Web UI、在线读 PDF、标签管理、统计面板
- **P3 AI**：RTX 4060 Ti 跑 bge-m3 向量化 → RAG 问答（带引用）→ MCP 接口，供 opencode/agent 直接查库
- **P4 可选**：知识图谱可视化（links 表）、“知识体检报告”（缺口/死链/重复）

P2–P4 各自单独立项，不纳入 P1 实施计划；P1 只交付地基能力。

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| 论坛反爬 / 登录失效 | 低频 + inbox 人工兜底；连接器互相隔离 |
| 来源改版导致连接器腐化 | fixtures 回归测试 + 健康报告定位故障源 |
| 磁盘膨胀 | 默认 300GB 预警线（可配）；GitHub 只存索引不 clone |
| 版权 | 仅个人学习自用，不重分发；书籍以本地入库为主 |
| 维护成本 | 一切配置 YAML 化；单源故障不影响全局 |

## 11. 关键决策记录

| 决策点 | 结论 | 理由 |
|---|---|---|
| 总体路线 | 分阶段：先地基后门面 | 快速可用，架构不返工 |
| 架构模式 | 统一资产管道（方案 A） | 单机场景兼顾增量、跨源关联与 AI 扩展 |
| 检索栈 | Python + SQLite + Meilisearch | 16GB 内存下轻量；中文友好；可平滑接向量检索 |
| 采集节奏 | 自动定时增量 | 长期滚雪球 |
| 语言策略 | 中文优先、英文并重 | 中文源解析规则先做，英文源按需增量 |
| 书籍通道 | 本地文件入库 + 书目清单 + 合法公开源 | 规避盗版爬虫风险，工具只管入库编目 |

## 12. 成功标准

1. 一条命令完成全量 / 增量更新
2. 任意关键词中文搜索 < 1s，覆盖书籍 / 帖子 / 漏洞 / 仓库
3. 断网离线可用（本地文件 + SQLite + FTS5）
4. 数据完全本地自有，可迁移、可备份
5. P3 完成后，AI agent 可通过 MCP 查询知识库
