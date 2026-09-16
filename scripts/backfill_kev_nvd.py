"""KEV 资产 NVD 结构化回填：为只有 KEV 摘要的漏洞补充 CVSS/CWE/参考链接。

可重复运行：只处理 cves.cvss 为空的资产，中断后重跑自动续。
用法：.venv\\Scripts\\python.exe scripts\\backfill_kev_nvd.py [--limit N] [--delay 6.5]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time

from seckb.config import load_settings
from seckb.connectors.nvd import API_ROOT, _cve_item
from seckb.net import FetchError, build_client, fetch_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条（0 = 全部）")
    parser.add_argument("--delay", type=float, default=6.5, help="每次请求间隔秒数（NVD 无 key 限速 5 次/30 秒）")
    args = parser.parse_args()

    settings = load_settings()
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT a.id, a.source_id
        FROM assets a JOIN cves c ON c.asset_id = a.id
        WHERE a.type = 'cve' AND a.source = 'kev' AND c.cvss IS NULL
        ORDER BY a.id
        """
    ).fetchall()
    if args.limit:
        rows = rows[: args.limit]
    total = len(rows)
    print(f"待回填 {total} 条", flush=True)

    client = build_client(timeout=60)
    updated = missing = failed = 0
    for index, row in enumerate(rows, 1):
        cve_id = row["source_id"]
        try:
            data = fetch_json(client, API_ROOT, params={"cveId": cve_id}, attempts=2)
        except FetchError as exc:
            failed += 1
            print(f"[{index}/{total}] {cve_id} 请求失败: {exc}", flush=True)
            time.sleep(20)
            continue
        vulnerabilities = data.get("vulnerabilities") or []
        if not vulnerabilities:
            missing += 1
        else:
            extra = _cve_item(vulnerabilities[0]).extra
            conn.execute(
                """
                UPDATE cves SET cve_id = ?, cvss = ?, cwe = ?, poc_refs = ?
                WHERE asset_id = ?
                """,
                (
                    extra.get("cve_id"),
                    extra.get("cvss"),
                    extra.get("cwe"),
                    json.dumps(extra.get("poc_refs") or [], ensure_ascii=False),
                    row["id"],
                ),
            )
            conn.commit()
            updated += 1
        if index % 25 == 0 or index == total:
            print(
                f"[{index}/{total}] updated={updated} missing={missing} failed={failed}",
                flush=True,
            )
        time.sleep(args.delay)
    print(f"完成 updated={updated} missing={missing} failed={failed}", flush=True)


if __name__ == "__main__":
    main()
