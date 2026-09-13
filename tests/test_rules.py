from seckb.pipeline.rules import (
    extract_attack_ids,
    extract_cves,
    extract_snippets,
    extract_tools,
)


def test_extract_cves_sorted_unique():
    text = "利用 cve-2021-44228 与 CVE-2021-44228，还有 CVE-2017-0144。"
    assert extract_cves(text) == ["CVE-2017-0144", "CVE-2021-44228"]


def test_extract_tools_word_boundary():
    text = "用 sqlmap 跑一下，配合 nmap 扫描；sqlmaptool 不算。"
    assert extract_tools(text, ["sqlmap", "nmap"]) == ["nmap", "sqlmap"]


def test_extract_attack_ids():
    text = "T1059.001 PowerShell, T1003 credential dumping"
    assert extract_attack_ids(text) == ["T1003", "T1059.001"]


def test_extract_snippets_kinds():
    md = """
```bash
nmap -sV -p- 10.0.0.1
```
```bash
for i in $(seq 1 10); do echo $i; done
echo done
```
```python
# payload: reverse shell
import socket
```
```php
<?php echo 1; ?>
```
"""
    snippets = extract_snippets(md)
    kinds = [(s.kind, s.lang) for s in snippets]
    assert kinds == [
        ("oneliner", "bash"),
        ("command", "bash"),
        ("payload", "python"),
        ("code", "php"),
    ]
    assert "nmap -sV" in snippets[0].content
