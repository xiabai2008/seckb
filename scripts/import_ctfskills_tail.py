"""补收 ljagiello/ctf-skills 被 safe-delete 守卫打断的尾部文件（一次性脚本）。

背景：collect 管道单轮触发沙箱批量删除守卫（阈值 50）后中途退出，
剩余 26 篇（ctf-web 全部 + unicorn-emulation + 2 个 SKILL）未入库。
本脚本直接下载原文并走 import_file API 带 source 元数据导入；
importer 对 markdown 导入后 unlink 源文件（26 次 < 50 阈值）。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "D:/HZR_PROJECTS/seckb")
import httpx  # noqa: E402

from seckb.config import load_settings  # noqa: E402
from seckb.db.connection import init_db  # noqa: E402
from seckb.pipeline.importer import import_file  # noqa: E402

REPO = "ljagiello/ctf-skills"
RAW = "https://raw.githubusercontent.com/ljagiello/ctf-skills/HEAD/"
DB = "D:/SecurityKB/meta/catalog.db"

missing = [
    "ctf-reverse/unicorn-emulation.md",
    "ctf-web/SKILL.md",
    "ctf-web/auth-and-access-2.md",
    "ctf-web/auth-and-access.md",
    "ctf-web/auth-infra.md",
    "ctf-web/auth-jwt.md",
    "ctf-web/client-side-advanced.md",
    "ctf-web/client-side.md",
    "ctf-web/cves.md",
    "ctf-web/field-notes.md",
    "ctf-web/node-and-prototype.md",
    "ctf-web/pat-reference.md",
    "ctf-web/python-requests.md",
    "ctf-web/server-side-2.md",
    "ctf-web/server-side-advanced-2.md",
    "ctf-web/server-side-advanced-3.md",
    "ctf-web/server-side-advanced-4.md",
    "ctf-web/server-side-advanced.md",
    "ctf-web/server-side-deser.md",
    "ctf-web/server-side-exec-2.md",
    "ctf-web/server-side-exec.md",
    "ctf-web/server-side.md",
    "ctf-web/sql-injection.md",
    "ctf-web/web3.md",
    "ctf-writeup/SKILL.md",
    "solve-challenge/SKILL.md",
]

con = sqlite3.connect(DB)
row = con.execute(
    "SELECT source FROM assets WHERE source_url LIKE '%ljagiello%' LIMIT 1"
).fetchone()
source = row[0] if row else "github_docs_std"
con.close()
print("reuse source:", source)

settings = load_settings(Path("D:/HZR_PROJECTS/seckb/config"))
conn = init_db(settings.kb_root)
staging = settings.kb_root / "meta" / "tmp" / "ctfskills-manual"
staging.mkdir(parents=True, exist_ok=True)

client = httpx.Client(timeout=30, follow_redirects=True)
ok, fail = 0, []
for path in missing:
    resp = client.get(RAW + path)
    if resp.status_code != 200 or not resp.text.strip():
        fail.append(path)
        continue
    local = staging / path.replace("/", "__")
    local.write_text(resp.text, encoding="utf-8")
    report = import_file(
        conn,
        settings,
        local,
        asset_type="post",
        source=source,
        source_url=f"https://github.com/{REPO}/blob/HEAD/{path}",
        source_id=f"{REPO}/{path}",
    )
    tag = report.status
    if tag == "imported":
        ok += 1
    elif tag != "duplicated":
        fail.append(f"{path} ({tag})")
    print(f"{tag:12s} {path}")
conn.close()
print(f"\nimported={ok} fail={len(fail)}")
for f in fail:
    print("  FAIL:", f)
