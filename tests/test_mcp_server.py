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
