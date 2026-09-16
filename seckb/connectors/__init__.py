from __future__ import annotations

import httpx

from seckb.connectors.base import Connector
from seckb.connectors.exploitdb import ExploitDBConnector
from seckb.connectors.github import GitHubConnector
from seckb.connectors.github_docs import GitHubDocsConnector
from seckb.connectors.kev import KEVConnector
from seckb.connectors.nvd import NVDConnector
from seckb.connectors.rss import RSSConnector
from seckb.connectors.vulhub import VulhubConnector


def build_connector(name: str, config: dict, client: httpx.Client) -> Connector:
    kind = config.get("type")
    if kind == "rss":
        return RSSConnector(name, list(config.get("feeds") or []), client)
    if kind == "github":
        return GitHubConnector(
            name,
            client,
            queries=list(config.get("search_queries") or []),
            awesome_repos=list(config.get("awesome_repos") or []),
        )
    if kind == "github_docs":
        return GitHubDocsConnector(
            name,
            client,
            repos=list(config.get("repos") or []),
        )
    if kind == "nvd":
        return NVDConnector(
            name,
            client,
            days_back=int(config.get("days_back", 7)),
            max_pages=int(config.get("max_pages", 5)),
        )
    if kind == "kev":
        return KEVConnector(name, client)
    if kind == "exploitdb":
        return ExploitDBConnector(name, client, max_rows=int(config.get("max_rows", 500)))
    if kind == "vulhub":
        return VulhubConnector(name, client)
    raise ValueError(f"未知连接器类型: {kind}")
