from __future__ import annotations

PROMPT_TEMPLATE = """你是网络安全知识库的编目助手。阅读下面的资料，输出一个 JSON 对象（不要输出任何其它文字）：
{{"summary": "一到两句话的摘要", "key_takeaways": ["要点1", "要点2"], "tags": ["标签1", "标签2"], "entities": {{"cve": [], "tool": [], "attack": [], "owasp": [], "product": []}}, "snippets": [{{"kind": "command|payload|oneliner|code", "lang": "bash", "tool": "nmap", "content": "可执行的命令或载荷原文", "context": "用途说明"}}]}}

要求：
- tags 用中文或英文短词，3~8 个
- entities 只填资料中真实出现的 CVE 编号、工具名、ATT&CK 技术号、OWASP 分类、产品名
- snippets 只提取资料中的命令、载荷、代码，不要杜撰；最多 6 条，只保留最核心的
- summary 控制在 120 字以内
- summary 必须基于资料内容

标题：{title}

正文：
{text}
"""


def build_prompt(title: str, text: str, *, max_chars: int = 12000) -> str:
    clipped = text[:max_chars]
    return PROMPT_TEMPLATE.format(title=title, text=clipped)
