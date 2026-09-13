from __future__ import annotations

import re

from seckb.models import SnippetDraft

CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
ATTACK_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b")
_FENCE_RE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
_PAYLOAD_MARK_RE = re.compile(r"^\s*(?:#|//|<!--)\s*(payload|exploit|poc)", re.IGNORECASE)

SHELL_LANGS = {"bash", "sh", "shell", "zsh", "powershell", "ps1", "cmd", "bat", "console"}
CODE_LANGS = {
    "python", "py", "php", "javascript", "js", "typescript", "ts",
    "java", "csharp", "cs", "go", "ruby", "rb", "perl", "c", "cpp",
}


def extract_cves(text: str) -> list[str]:
    return sorted({match.group(0).upper() for match in CVE_RE.finditer(text)})


def extract_attack_ids(text: str) -> list[str]:
    return sorted({match.group(0).upper() for match in ATTACK_RE.finditer(text)})


def extract_tools(text: str, tools: list[str]) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    for tool in tools:
        pattern = rf"(?<![a-z0-9_-]){re.escape(tool.lower())}(?![a-z0-9_-])"
        if re.search(pattern, lower):
            found.append(tool)
    return sorted(found)


def extract_snippets(md: str) -> list[SnippetDraft]:
    snippets: list[SnippetDraft] = []
    for match in _FENCE_RE.finditer(md):
        lang = match.group(1).strip().lower() or None
        body = match.group(2).strip("\n")
        if not body.strip():
            continue
        kind = "code"
        if lang in SHELL_LANGS:
            kind = "oneliner" if "\n" not in body.strip() else "command"
        elif lang in CODE_LANGS:
            kind = "payload" if _PAYLOAD_MARK_RE.match(body) else "code"
        snippets.append(SnippetDraft(kind=kind, lang=lang, content=body))
    return snippets
