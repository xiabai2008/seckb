import json
from pathlib import Path

from seckb.enrich.queue import enqueue, process_jobs
from seckb.pipeline.importer import import_file
from seckb.utils.tokens import estimate_tokens

GOOD_JSON = json.dumps(
    {
        "summary": "fastjson 反序列化利用总结。",
        "key_takeaways": ["需要 autotype 开启"],
        "tags": ["反序列化", "fastjson"],
        "entities": {"cve": ["CVE-2017-18349"], "tool": ["marshalsec"]},
        "snippets": [
            {
                "kind": "command",
                "lang": "bash",
                "tool": "java",
                "content": "java -jar marshalsec.jar",
                "context": "启动 LDAP",
            }
        ],
    }
)


class FakeLLM:
    model = "fake-model"

    def __init__(self, response=GOOD_JSON, error=None):
        self.response = response
        self.error = error
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self.error:
            raise RuntimeError(self.error)
        return self.response


def make_asset(kb, tmp_path: Path) -> int:
    src = tmp_path / "post.md"
    src.write_text(
        "# fastjson 反序列化\n\nCVE-2017-18349 利用记录，使用 marshalsec 启动 LDAP。\n\n"
        "```bash\njava -jar marshalsec.jar\n```\n",
        encoding="utf-8",
    )
    return import_file(kb.conn, kb.settings, src).asset_id


def test_process_jobs_creates_card_and_entities(kb, tmp_path: Path):
    asset_id = make_asset(kb, tmp_path)
    enqueue(kb.conn, asset_id)
    report = process_jobs(kb.conn, kb.settings, FakeLLM())
    assert report.succeeded == 1
    card = kb.conn.execute("SELECT * FROM cards WHERE asset_id = ?", (asset_id,)).fetchone()
    assert card["model"] == "fake-model"
    assert "fastjson" in card["summary"]
    tags = json.loads(
        kb.conn.execute("SELECT tags FROM assets WHERE id = ?", (asset_id,)).fetchone()["tags"]
    )
    assert "反序列化" in tags
    entities = kb.conn.execute(
        """SELECT e.kind, e.name FROM asset_entities ae JOIN entities e ON e.id = ae.entity_id
           WHERE ae.asset_id = ?""",
        (asset_id,),
    ).fetchall()
    pairs = {(row["kind"], row["name"]) for row in entities}
    assert ("cve", "CVE-2017-18349") in pairs
    assert ("tool", "marshalsec") in pairs
    llm_snippet = kb.conn.execute(
        "SELECT * FROM snippets WHERE asset_id = ? AND content = 'java -jar marshalsec.jar'",
        (asset_id,),
    ).fetchone()
    assert llm_snippet is not None
    job = kb.conn.execute("SELECT * FROM jobs WHERE asset_id = ?", (asset_id,)).fetchone()
    assert job["status"] == "done"


def test_process_jobs_respects_input_budget(kb, tmp_path: Path):
    asset_id = make_asset(kb, tmp_path)
    enqueue(kb.conn, asset_id)
    kb.settings.enrich = {"queue": {"max_input_tokens": 10}}
    provider = FakeLLM()
    process_jobs(kb.conn, kb.settings, provider)
    prompt = provider.calls[0]
    body = prompt.split("正文：", 1)[1]
    assert estimate_tokens(body) <= 40


def test_process_jobs_retries_then_fails(kb, tmp_path: Path):
    asset_id = make_asset(kb, tmp_path)
    enqueue(kb.conn, asset_id)
    kb.settings.enrich = {"queue": {"max_attempts": 1}}
    report = process_jobs(kb.conn, kb.settings, FakeLLM(error="llm down"))
    assert report.failed == 1
    job = kb.conn.execute("SELECT * FROM jobs WHERE asset_id = ?", (asset_id,)).fetchone()
    assert job["status"] == "failed"
    assert job["attempts"] == 1
    assert "llm down" in job["last_error"]


def test_process_jobs_skips_done_jobs(kb, tmp_path: Path):
    asset_id = make_asset(kb, tmp_path)
    enqueue(kb.conn, asset_id)
    process_jobs(kb.conn, kb.settings, FakeLLM())
    report = process_jobs(kb.conn, kb.settings, FakeLLM())
    assert report.processed == 0
