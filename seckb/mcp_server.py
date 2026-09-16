from __future__ import annotations

import sqlite3

from mcp.server.mcpserver import MCPServer

from seckb import tools as kb_tools
from seckb.config import Settings, load_settings
from seckb.db.connection import init_db
from seckb.retrieval import HybridRetriever, build_retriever


def build_server(
    conn: sqlite3.Connection, settings: Settings, retriever: HybridRetriever
) -> MCPServer:
    server = MCPServer("seckb")

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
