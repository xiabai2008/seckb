from seckb.collect import collect_all, run_source
from seckb.connectors import build_connector
from seckb.connectors.base import RawItem


class FakeConnector:
    def __init__(self, name, items, new_cursor=None, error=None):
        self.name = name
        self.items = items
        self.new_cursor = new_cursor
        self.error = error
        self.cursors: list[str | None] = []

    def fetch(self, cursor):
        self.cursors.append(cursor)
        if self.error:
            raise RuntimeError(self.error)
        return self.items, self.new_cursor


def test_run_source_stores_cursor_and_run_log(kb):
    connector = FakeConnector(
        "fake",
        [RawItem(source_id="a1", title="条目一", content="内容一。", url=None)],
        new_cursor="2026-09-01",
    )
    report = run_source(kb.conn, kb.settings, connector)
    assert report.imported == 1
    row = kb.conn.execute("SELECT * FROM sources WHERE name = 'fake'").fetchone()
    assert row["last_cursor"] == "2026-09-01"
    assert row["health"] == "ok"
    run = kb.conn.execute("SELECT * FROM runs WHERE source = 'fake'").fetchone()
    assert run["imported"] == 1
    assert run["finished_at"] is not None


def test_run_source_failure_marks_health(kb):
    connector = FakeConnector("fake", [], error="boom")
    report = run_source(kb.conn, kb.settings, connector)
    assert report.error == "boom"
    row = kb.conn.execute("SELECT * FROM sources WHERE name = 'fake'").fetchone()
    assert row["health"] == "error"


def test_collect_all_isolates_failures(kb, monkeypatch):
    import seckb.collect as collect_mod

    good = FakeConnector("good", [RawItem(source_id="g1", title="g", content="g。")])
    bad = FakeConnector("bad", [], error="down")
    monkeypatch.setattr(
        collect_mod, "build_connectors", lambda settings: {"good": good, "bad": bad}
    )
    reports = collect_all(kb.conn, kb.settings)
    by_name = {r.source: r for r in reports}
    assert by_name["good"].imported == 1
    assert by_name["bad"].error == "down"


def test_build_connector_registry():
    from seckb.net import build_client

    client = build_client()
    connector = build_connector("rss", {"type": "rss", "feeds": ["https://e.com/f"]}, client)
    assert connector.name == "rss"
    connector2 = build_connector("nvd", {"type": "nvd", "days_back": 3}, client)
    assert connector2.name == "nvd"
    client.close()
