from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from seckb.connectors.base import RawItem
from seckb.net import fetch_json

TREE_URL = "https://api.github.com/repos/vulhub/vulhub/git/trees/master?recursive=1"
TREE_PAGE = "https://github.com/vulhub/vulhub/tree/master"


class VulhubConnector:
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
        data = fetch_json(self.client, TREE_URL, sleep=self.sleep)
        nodes = data.get("tree") or []
        categories = {
            node["path"]
            for node in nodes
            if node.get("type") == "tree" and "/" not in node.get("path", "")
        }
        envs: dict[str, list[str]] = {}
        for node in nodes:
            path = node.get("path") or ""
            if "/" not in path or node.get("type") != "blob":
                continue
            category, _, rest = path.partition("/")
            if category not in categories or not rest:
                continue
            env = f"{category}/{rest.split('/')[0]}"
            if "/" in rest:
                envs.setdefault(env, []).append(path)
        items: list[RawItem] = []
        for env, files in sorted(envs.items()):
            name = env.rsplit("/", 1)[-1]
            url = f"{TREE_PAGE}/{env}"
            content = "\n".join(
                [f"## Vulhub 环境 {name}", "", f"- 环境目录: {url}", "", "包含文件:", ""]
                + [f"- {path}" for path in sorted(files)]
            )
            items.append(
                RawItem(
                    source_id=f"vulhub:{name}",
                    title=f"Vulhub {name}",
                    content=content,
                    asset_type="writeup",
                    url=url,
                    extra={"site": "vulhub"},
                )
            )
        return items, cursor
