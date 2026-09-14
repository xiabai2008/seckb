from __future__ import annotations

import os
import re
import time
from collections.abc import Callable

import httpx

from seckb.connectors.base import RawItem
from seckb.net import fetch_json, fetch_text

API_ROOT = "https://api.github.com"
RAW_ROOT = "https://raw.githubusercontent.com"
REPO_LINK_RE = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)")
RESERVED_OWNERS = {
    "features", "topics", "sponsors", "settings", "notifications", "explore",
    "marketplace", "apps", "about", "pricing", "login", "join", "orgs", "users",
}


def _repo_item(repo: dict) -> RawItem:
    full_name = repo["full_name"]
    description = repo.get("description") or ""
    topics = repo.get("topics") or []
    stars = repo.get("stargazers_count") or 0
    content = "\n".join(
        part
        for part in (
            description,
            "",
            f"- Stars: {stars}",
            f"- Language: {repo.get('language') or '未知'}",
            f"- Topics: {', '.join(topics)}" if topics else "",
            f"- 仓库地址: {repo.get('html_url')}",
        )
        if part != ""
    )
    owner, _, name = full_name.partition("/")
    return RawItem(
        source_id=f"repo:{full_name}",
        title=full_name,
        content=content,
        asset_type="repo",
        url=repo.get("html_url"),
        published_at=repo.get("pushed_at"),
        extra={
            "owner": owner,
            "name": name,
            "stars": stars,
            "forks": repo.get("forks_count"),
            "language": repo.get("language"),
            "topics": topics,
            "clone_url": repo.get("clone_url"),
            "license": (repo.get("license") or {}).get("spdx_id"),
            "archived": repo.get("archived"),
            "last_commit": repo.get("pushed_at"),
        },
    )


def _extract_repo_links(readme: str, exclude: str) -> set[str]:
    found: set[str] = set()
    for owner, name in REPO_LINK_RE.findall(readme):
        if owner.lower() in RESERVED_OWNERS:
            continue
        full_name = f"{owner}/{name}"
        if full_name.lower() == exclude.lower():
            continue
        found.add(full_name)
    return found


class GitHubConnector:
    def __init__(
        self,
        name: str,
        client: httpx.Client,
        *,
        queries: list[str] | None = None,
        awesome_repos: list[str] | None = None,
        per_page: int = 50,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.client = client
        self.queries = queries or []
        self.awesome_repos = awesome_repos or []
        self.per_page = per_page
        self.sleep = sleep

    def _headers(self) -> dict:
        token = os.environ.get("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def fetch(self, cursor: str | None) -> tuple[list[RawItem], str | None]:
        items: list[RawItem] = []
        for query in self.queries:
            data = fetch_json(
                self.client,
                f"{API_ROOT}/search/repositories",
                params={
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": self.per_page,
                },
                headers=self._headers(),
                sleep=self.sleep,
            )
            for repo in data.get("items", []):
                items.append(_repo_item(repo))
        for full_name in self.awesome_repos:
            readme = fetch_text(
                self.client,
                f"{RAW_ROOT}/{full_name}/HEAD/README.md",
                sleep=self.sleep,
            )
            for linked in sorted(_extract_repo_links(readme, full_name)):
                owner, _, name = linked.partition("/")
                url = f"https://github.com/{owner}/{name}"
                items.append(
                    RawItem(
                        source_id=f"awesome:{owner}/{name}",
                        title=f"{owner}/{name}",
                        content=f"来自 awesome 列表 {full_name} 的推荐仓库。\n\n- 仓库地址: {url}",
                        asset_type="repo",
                        url=url,
                        extra={
                            "owner": owner,
                            "name": name,
                            "topics": [],
                            "awesome_list": full_name,
                        },
                    )
                )
        return items, cursor
