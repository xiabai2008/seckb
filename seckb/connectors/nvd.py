from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from seckb.connectors.base import RawItem
from seckb.net import fetch_json

API_ROOT = "https://services.nvd.nist.gov/rest/json/cves/2.0"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.000"


def _cvss_score(cve: dict) -> float | None:
    metrics = cve.get("metrics") or {}
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(key) or []
        if entries:
            return (entries[0].get("cvssData") or {}).get("baseScore")
    return None


def _cwe(cve: dict) -> str | None:
    for weakness in cve.get("weaknesses") or []:
        for description in weakness.get("description") or []:
            value = description.get("value")
            if value and value.startswith("CWE-"):
                return value
    return None


def _description(cve: dict) -> str:
    for entry in cve.get("descriptions") or []:
        if entry.get("lang") == "en":
            return entry.get("value") or ""
    return ""


def _cve_item(vuln: dict) -> RawItem:
    cve = vuln["cve"]
    cve_id = cve["id"]
    description = _description(cve)
    score = _cvss_score(cve)
    cwe = _cwe(cve)
    references = [ref.get("url") for ref in cve.get("references") or [] if ref.get("url")]
    lines = [f"## {cve_id}", "", description, ""]
    if score is not None:
        lines.append(f"- CVSS: {score}")
    if cwe:
        lines.append(f"- CWE: {cwe}")
    if references:
        lines.extend(["", "### 参考链接", ""])
        lines.extend(f"- {url}" for url in references[:10])
    return RawItem(
        source_id=cve_id,
        title=cve_id,
        content="\n".join(lines),
        asset_type="cve",
        url=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
        published_at=cve.get("published"),
        extra={"cve_id": cve_id, "cvss": score, "cwe": cwe, "poc_refs": references},
    )


class NVDConnector:
    def __init__(
        self,
        name: str,
        client: httpx.Client,
        *,
        days_back: int = 7,
        max_pages: int = 5,
        page_delay: float = 6.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.client = client
        self.days_back = days_back
        self.max_pages = max_pages
        self.page_delay = page_delay
        self.sleep = sleep

    def _headers(self) -> dict:
        api_key = os.environ.get("NVD_API_KEY")
        return {"apiKey": api_key} if api_key else {}

    def fetch(self, cursor: str | None) -> tuple[list[RawItem], str | None]:
        end = datetime.now(UTC)
        start = cursor or (end - timedelta(days=self.days_back)).strftime(TIME_FORMAT)
        end_str = end.strftime(TIME_FORMAT)
        items: list[RawItem] = []
        start_index = 0
        for _ in range(self.max_pages):
            data = fetch_json(
                self.client,
                API_ROOT,
                params={
                    "lastModStartDate": start,
                    "lastModEndDate": end_str,
                    "resultsPerPage": 200,
                    "startIndex": start_index,
                },
                headers=self._headers(),
                sleep=self.sleep,
            )
            for vuln in data.get("vulnerabilities", []):
                items.append(_cve_item(vuln))
            page_size = data.get("resultsPerPage") or 200
            start_index += page_size
            if start_index >= (data.get("totalResults") or 0):
                break
            self.sleep(self.page_delay)
        return items, end_str
