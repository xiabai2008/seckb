from __future__ import annotations

import time
from collections.abc import Callable

import feedparser
import httpx

from seckb.connectors.base import RawItem
from seckb.net import fetch_bytes
from seckb.pipeline.normalize import html_to_markdown


class RSSConnector:
    def __init__(
        self,
        name: str,
        feeds: list[str],
        client: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.feeds = feeds
        self.client = client
        self.sleep = sleep

    def fetch(self, cursor: str | None) -> tuple[list[RawItem], str | None]:
        items: list[RawItem] = []
        for feed_url in self.feeds:
            raw = fetch_bytes(self.client, feed_url, sleep=self.sleep)
            parsed = feedparser.parse(raw)
            for entry in parsed.entries:
                link = (entry.get("link") or "").strip()
                source_id = (entry.get("id") or link).strip()
                if not source_id:
                    continue
                title = (entry.get("title") or link).strip()
                body = entry.get("summary") or entry.get("description") or ""
                if "<" in body:
                    _, body = html_to_markdown(body)
                items.append(
                    RawItem(
                        source_id=source_id,
                        title=title,
                        content=body.strip(),
                        asset_type="post",
                        url=link or None,
                        published_at=entry.get("published") or entry.get("updated"),
                        extra={"site": feed_url},
                    )
                )
        return items, cursor
