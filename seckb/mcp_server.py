from __future__ import annotations

import logging
import sqlite3

from mcp.server.mcpserver import MCPServer

from seckb import tools as kb_tools
from seckb.config import Settings, load_settings
from seckb.db.connection import init_db
from seckb.retrieval import HybridRetriever, build_retriever
from seckb.services import ServiceManager


def configure_logging() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def build_server(
    conn: sqlite3.Connection,
    settings: Settings,
    retriever: HybridRetriever,
    services: ServiceManager | None = None,
) -> MCPServer:
    server = MCPServer("seckb")
    manager = services or ServiceManager(settings)

    @server.tool()
    def kb_search(
        query: str, type: str | None = None, tag: str | None = None, limit: int = 8
    ) -> dict:
        """混合检索本地网络安全知识库（漏洞库/帖子/仓库/靶场/书籍），返回带摘要、标签与出处的候选列表。query 支持中文或英文关键词、CVE 编号或自然语言问题。若返回 degraded 非空，说明部分检索后端未运行，可先用 kb_services 启动后重试。"""
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
        asset_id: int | None = None,
        limit: int = 10,
    ) -> dict:
        """检索可直接执行的命令/载荷/代码片段（含工具名与上下文），适合信息收集、漏洞利用与绕过场景取用。可用 asset_id 只看某个资产内的片段。"""
        return kb_tools.kb_snippets(
            conn, query=query, tool=tool, kind=kind, asset_id=asset_id, limit=limit
        )

    @server.tool()
    def kb_services(action: str = "status", what: str = "all") -> dict:
        """查看或启动知识库后端服务。检索由 FTS5（内置）+ Meilisearch + 语义向量（Ollama）三路组成；
        当 kb_search 返回的 degraded 非空（例如 ["meili","vector"]）说明有后端未运行、检索质量下降，
        此时可调用本工具 action="start" 拉起后端，然后重新检索。

        action: status=查看各服务状态；start=启动服务。
        what（仅 start 时使用）: search=检索后端（Ollama+Meilisearch）；collect=自动采集（daemon）；all=全部。
        出于安全考虑不提供 stop（如需停止请由用户在看板或桌面脚本操作）。"""
        if action == "status":
            return manager.status()
        if action == "start":
            try:
                return manager.start(what)
            except ValueError as exc:
                return {"error": str(exc)}
        return {"error": f"不支持的操作: {action}（仅支持 status / start）"}

    return server


def run_stdio() -> None:
    configure_logging()
    settings = load_settings()
    conn = init_db(settings.kb_root)
    retriever = build_retriever(conn, settings)
    server = build_server(conn, settings, retriever)
    server.run()
