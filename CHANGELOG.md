# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与[语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

暂无。

## [0.1.0] - 2026-10-18

首个版本：本地、离线可用、面向 AI Agent 的安全知识库。

### 新增

**采集**

- 连接器：NVD（增量游标 + 分窗拉取）、CISA KEV、Exploit-DB、Vulhub、RSS、
  GitHub（搜索 + Awesome 清单）、GitHub 文档型知识库
  （PayloadsAllTheThings / HackTricks / GTFOBins / Awesome-POC / 1earn 等）、`inbox` 人工投递
- 采集编排：来源注册表、断点游标、`runs` 运行日志、单源故障隔离
- APScheduler 守护进程：定时采集 + 富化 + 向量 + 索引

**结构化**

- 归一化：HTML / PDF / EPUB / Markdown → 统一 Markdown，图片本地化
- 标题感知切块：带重叠、面包屑、页码、token 数
- 去重：sha256 精确 + SimHash 近似 + URL 规范化
- 规则抽取：CVE / 工具 / ATT&CK / 命令载荷片段

**富化**

- 异步队列：领取 + 并发 + 重试 + `--drain` 排空
- OpenAI 兼容 LLM Provider；产出知识卡片、标签、实体、片段
- 峰谷调度：峰时跳过富化；关闭 thinking 显著降低输出 token

**检索**

- 四路召回：FTS5（离线兜底）/ 中文别名扩展 / Meilisearch / LanceDB 向量（bge-m3）
- RRF 融合排序；单路失败优雅降级并写进 `degraded`
- 中文花名映射（27 组：永恒之蓝、脏牛、破壳、冰蝎…）

**Agent 接口**

- MCP Server（stdio）：`kb_search` / `kb_card` / `kb_get` / `kb_snippets` / `kb_services`
- HTTP API（FastAPI）：`/search` `/card/{id}` `/get/{id}` `/snippets` `/stats`
- CLI：`init` `import` `scan` `search` `card` `get` `snippets` `collect` `enrich`
  `embed` `index` `sources` `eval` `stats` `daemon` `serve` `mcp`
- 三级粒度取用：卡片（200–400 token）/ 正文切片（按 `max_tokens` 硬截断）/ 命令片段

**看板与运维**

- 本地看板：概览图表、实时混合检索、资产浏览、详情抽屉、服务一键启停
- 主题系统：玄墨（暗）/ 纸本（亮）
- 运维脚本：一键启停、知识库体检（`kb_health`）、KEV→NVD 回填

**工程与协作**

- GitHub Actions CI：Ubuntu + Windows 双平台跑 `ruff check .` 与 `pytest`
- `CONTRIBUTING.md` / `SECURITY.md` / `CODE_OF_CONDUCT.md` / `CHANGELOG.md`
- GitHub issue 表单（Bug 报告 / 功能建议）与 PR 模板
- `.gitattributes`：统一换行符，显式声明二进制资源

### 变更

- README 重写：以「为什么做 / 怎么设计 / 效果如何」为主线，附真实运行截图与实测数据
  （热态检索中位 1.58s、`kb_get` 的 token 硬预算等）
- `pyproject.toml` 补 `readme` / `license` / `keywords` / `classifiers` / `project.urls`

### 修复

- **SSRF**：`pipeline/normalize.py` 的图片抓取此前会请求被采集页面里的任意 URL。
  现只允许公网 http(s)，解析后逐个校验 IP，并校验重定向每一跳；被拒的图片只跳过该图，不中断整篇入库
- **SSRF**：`services.py` 的服务探针此前接收任意 URL，等同通用请求器。现收敛到本机端点并校验解析结果
- `db/migrate.py` 去掉动态拼接的 SQL（SQLite 的 `PRAGMA` 不支持占位符，改为由迁移脚本自己写版本号，
  并在版本未推进时显式报错）
- `scripts/` 与 `tests/` 里硬编码的作者机器路径，改为按 `__file__` 推导或走配置
- LICENSE 清理为纯 MIT 正文（此前追加的说明段导致 GitHub 识别为 "Other"）
- 看板标题的版本号此前写死为 `v1.3`，与 `__version__` 不一致；现由 `__version__` 注入，并补了回归测试

### 工程

- `ruff check .` 清零（此前 `scripts/` 下有 11 处历史提示）

### 安全

- 第三方 Agent 指令型文档（`SKILL.md` / `AGENTS.md` 等）命中时，`kb_get` 会返回投毒警示横幅，
  明确告知 Agent：这是数据不是指令
- 检索核心全本地，仅富化需要外网；断网时关键词与向量检索仍可用

[Unreleased]: https://github.com/xiabai2008/seckb/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/xiabai2008/seckb/releases/tag/v0.1.0
