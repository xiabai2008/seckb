import json

import anyio

from seckb.mcp_server import build_server
from seckb.retrieval import HybridRetriever


class FakeServiceManager:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"ollama": {"running": True}, "retrieval_ready": True}

    def start(self, what):
        self.calls.append(("start", what))
        if what not in ("search", "collect", "all"):
            raise ValueError("未知目标")
        return {
            "what": what,
            "actions": [{"target": "ollama", "action": "started"}],
            "status": self.status(),
        }

    def stop(self, what):
        self.calls.append(("stop", what))
        return {"what": what, "actions": [], "status": self.status()}


def test_mcp_server_registers_expected_tools(kb):
    retriever = HybridRetriever(kb.conn, kb.settings)
    server = build_server(kb.conn, kb.settings, retriever)
    tools = anyio.run(server.list_tools)
    names = {tool.name for tool in tools}
    assert names == {"kb_search", "kb_card", "kb_get", "kb_snippets", "kb_services"}
    for tool in tools:
        assert tool.description


def test_mcp_kb_services_status_start_and_no_stop(kb):
    fake = FakeServiceManager()
    retriever = HybridRetriever(kb.conn, kb.settings)
    server = build_server(kb.conn, kb.settings, retriever, services=fake)

    result = anyio.run(server.call_tool, "kb_services", {"action": "status"})
    payload = json.loads(result.content[0].text)
    assert payload["retrieval_ready"] is True

    result = anyio.run(server.call_tool, "kb_services", {"action": "start", "what": "search"})
    payload = json.loads(result.content[0].text)
    assert payload["actions"][0]["target"] == "ollama"
    assert fake.calls == [("start", "search")]

    result = anyio.run(server.call_tool, "kb_services", {"action": "start", "what": "bogus"})
    payload = json.loads(result.content[0].text)
    assert "error" in payload

    result = anyio.run(server.call_tool, "kb_services", {"action": "stop"})
    payload = json.loads(result.content[0].text)
    assert "error" in payload
    assert fake.calls == [("start", "search"), ("start", "bogus")]


def test_configure_logging_quiets_http_logs():
    import logging

    from seckb.mcp_server import configure_logging

    logging.getLogger("httpx").setLevel(logging.INFO)
    configure_logging()
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
