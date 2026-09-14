from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from seckb.connectors.base import RawItem
from seckb.net import fetch_json

KEV_URL = (
    "https://www.cisa.gov/sites/default/files/feeds/"
    "known_exploited_vulnerabilities.json"
)


class KEVConnector:
    def __init__(
        self,
        name: str,
        client: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.client = client
        self.sleep = sleep

    def fetch(self, cursor: str | None) -> tuple[list[RawItem], str | None]:
        data = fetch_json(self.client, KEV_URL, sleep=self.sleep)
        items: list[RawItem] = []
        for entry in data.get("vulnerabilities", []):
            cve_id = entry.get("cveID") or ""
            if not cve_id:
                continue
            content = "\n".join(
                [
                    f"## {cve_id}（在野利用）",
                    "",
                    f"- 漏洞名称: {entry.get('vulnerabilityName') or '未知'}",
                    f"- 厂商: {entry.get('vendorProject') or '未知'}",
                    f"- 产品: {entry.get('product') or '未知'}",
                    f"- 加入 KEV 日期: {entry.get('dateAdded') or '未知'}",
                    "",
                    entry.get("shortDescription") or "",
                    "",
                    f"处置建议: {entry.get('requiredAction') or '及时升级修复'}",
                ]
            )
            items.append(
                RawItem(
                    source_id=cve_id,
                    title=f"{cve_id} KEV",
                    content=content,
                    asset_type="cve",
                    url="https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
                    published_at=entry.get("dateAdded"),
                    extra={"in_kev": True, "cve_id": cve_id},
                )
            )
        return items, cursor
