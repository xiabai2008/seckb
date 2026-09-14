from __future__ import annotations

import json
from dataclasses import dataclass, field

ENTITY_KINDS = ("cve", "tool", "attack", "owasp", "product")


class EnrichmentParseError(Exception):
    pass


@dataclass
class Enrichment:
    summary: str
    key_takeaways: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    snippets: list[dict] = field(default_factory=list)


def _str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def parse_enrichment(raw: str) -> Enrichment:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise EnrichmentParseError("响应中没有 JSON 对象")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise EnrichmentParseError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise EnrichmentParseError("JSON 顶层不是对象")
    summary = str(data.get("summary") or "").strip()
    if not summary:
        raise EnrichmentParseError("缺少 summary")
    entities_raw = data.get("entities") or {}
    entities = {
        kind: _str_list(entities_raw.get(kind)) for kind in ENTITY_KINDS
    }
    snippets: list[dict] = []
    for entry in data.get("snippets") or []:
        if not isinstance(entry, dict):
            continue
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        snippets.append(
            {
                "kind": str(entry.get("kind") or "code"),
                "lang": entry.get("lang"),
                "tool": entry.get("tool"),
                "content": content,
                "context": str(entry.get("context") or ""),
            }
        )
    return Enrichment(
        summary=summary,
        key_takeaways=_str_list(data.get("key_takeaways")),
        tags=_str_list(data.get("tags")),
        entities=entities,
        snippets=snippets,
    )
