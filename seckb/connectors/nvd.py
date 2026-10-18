from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from seckb.connectors.base import RawItem
from seckb.net import fetch_json

logger = logging.getLogger("seckb.connectors.nvd")

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
        window_days: float = 1.0,
        max_windows: int = 40,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.client = client
        self.days_back = days_back
        self.max_pages = max_pages
        self.page_delay = page_delay
        self.window_days = window_days
        self.max_windows = max_windows
        self.sleep = sleep

    def _headers(self) -> dict:
        api_key = os.environ.get("NVD_API_KEY")
        return {"apiKey": api_key} if api_key else {}

    def _fetch_window(self, start: datetime, end: datetime) -> tuple[list[RawItem], bool]:
        """拉取单个时间窗口内的全部变更，返回 (items, 是否被单次页数上限截断)。"""
        items: list[RawItem] = []
        start_index = 0
        total = 0
        for _ in range(self.max_pages):
            data = fetch_json(
                self.client,
                API_ROOT,
                params={
                    "lastModStartDate": start.strftime(TIME_FORMAT),
                    "lastModEndDate": end.strftime(TIME_FORMAT),
                    "resultsPerPage": 200,
                    "startIndex": start_index,
                },
                headers=self._headers(),
                sleep=self.sleep,
            )
            for vuln in data.get("vulnerabilities", []):
                items.append(_cve_item(vuln))
            page_size = data.get("resultsPerPage") or 200
            total = data.get("totalResults") or 0
            start_index += page_size
            if start_index >= total:
                return items, False
            self.sleep(self.page_delay)
        return items, start_index < total

    def _fetch_range(self, start: datetime, end: datetime, depth: int = 0) -> tuple[list[RawItem], bool]:
        """拉取 [start, end)，窗口内被截断时二分重试，避免静默丢数据。"""
        items, truncated = self._fetch_window(start, end)
        if not truncated or depth >= 4:
            if truncated:
                logger.warning(
                    "NVD 窗口 %s ~ %s 仍有条目未拉取（单次上限 %d 页），已放弃细分",
                    start.isoformat(),
                    end.isoformat(),
                    self.max_pages,
                )
            return items, truncated
        mid = start + (end - start) / 2
        left, left_truncated = self._fetch_range(start, mid, depth + 1)
        right, right_truncated = self._fetch_range(mid, end, depth + 1)
        return left + right, left_truncated or right_truncated

    def fetch(self, cursor: str | None) -> tuple[list[RawItem], str | None]:
        """按时间窗口推进游标。

        旧实现一次性拉 cursor→now 的全部变更，超过 max_pages*200 后静默截断，
        却仍把游标推进到 now，导致中间数据永久丢失。现改为按 window_days 分窗，
        窗口内超限则二分重试，游标只推进到已完整拉取的窗口末尾。
        """
        now = datetime.now(UTC)
        start_dt: datetime
        if cursor:
            try:
                start_dt = datetime.strptime(cursor, TIME_FORMAT).replace(tzinfo=UTC)
            except ValueError:
                start_dt = now - timedelta(days=self.days_back)
        else:
            start_dt = now - timedelta(days=self.days_back)

        items: list[RawItem] = []
        cursor_dt = start_dt
        for _ in range(self.max_windows):
            if cursor_dt >= now:
                break
            window_end = min(cursor_dt + timedelta(days=self.window_days), now)
            batch, truncated = self._fetch_range(cursor_dt, window_end)
            items.extend(batch)
            if truncated:
                # 该窗口无法完整拉取，游标停在窗口起点，下一轮重试（不会跳过数据）
                break
            cursor_dt = window_end
            if window_end >= now:
                break
        return items, cursor_dt.strftime(TIME_FORMAT)
