import pytest

from seckb.enrich.parser import EnrichmentParseError, parse_enrichment
from seckb.enrich.prompts import build_prompt

GOOD = """
{
  "summary": "介绍 fastjson 反序列化漏洞的利用方式。",
  "key_takeaways": ["影响 1.2.24 以下版本", "需要 autotype 开启"],
  "tags": ["反序列化", "fastjson"],
  "entities": {"cve": ["CVE-2017-18349"], "tool": ["marshalsec"], "attack": ["T1059"]},
  "snippets": [
    {"kind": "command", "lang": "bash", "tool": "java", "content": "java -jar marshalsec.jar", "context": "启动 LDAP 服务"}
  ]
}
"""


def test_parse_plain_json():
    result = parse_enrichment(GOOD)
    assert "fastjson" in result.summary
    assert result.key_takeaways[0].startswith("影响")
    assert result.tags == ["反序列化", "fastjson"]
    assert result.entities["cve"] == ["CVE-2017-18349"]
    assert result.snippets[0]["kind"] == "command"
    assert result.snippets[0]["tool"] == "java"


def test_parse_fenced_json():
    fenced = "```json\n" + GOOD + "\n```"
    assert parse_enrichment(fenced).summary == parse_enrichment(GOOD).summary


def test_parse_missing_summary_raises():
    with pytest.raises(EnrichmentParseError):
        parse_enrichment('{"key_takeaways": []}')


def test_parse_invalid_raises():
    with pytest.raises(EnrichmentParseError):
        parse_enrichment("这不是 JSON")


def test_snippets_without_content_are_dropped():
    raw = '{"summary": "s", "snippets": [{"kind": "code"}, {"content": "ls -la"}]}'
    result = parse_enrichment(raw)
    assert len(result.snippets) == 1
    assert result.snippets[0]["kind"] == "code"


def test_build_prompt_clips_text():
    prompt = build_prompt("标题", "x" * 50000)
    assert "标题" in prompt
    assert len(prompt) < 20000
