from __future__ import annotations

import json
import time
from collections.abc import Callable
from urllib.parse import quote

import httpx

from seckb.connectors.base import RawItem
from seckb.net import FetchError, fetch_json, fetch_text

API_ROOT = "https://api.github.com"
RAW_ROOT = "https://raw.githubusercontent.com"
DEFAULT_SUFFIXES = (".md", ".markdown")
DEFAULT_EXCLUDES = (".github/", "assets/", ".git/")


class GitHubDocsConnector:
    """整仓收录 GitHub 上的文档型知识库（Markdown / 无扩展名文本文件）。"""

    def __init__(
        self,
        name: str,
        client: httpx.Client,
        *,
        repos: list[dict],
        file_delay: float = 0.15,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.client = client
        self.repos = repos
        self.file_delay = file_delay
        self.sleep = sleep

    def _tree(self, repo: str) -> tuple[str, list[str]]:
        data = fetch_json(
            self.client,
            f"{API_ROOT}/repos/{repo}/git/trees/HEAD",
            params={"recursive": "1"},
            sleep=self.sleep,
        )
        sha = data.get("sha") or ""
        paths = [node["path"] for node in data.get("tree", []) if node.get("type") == "blob"]
        return sha, paths

    def _select(self, paths: list[str], config: dict) -> list[str]:
        includes = list(config.get("include_prefixes") or [])
        excludes = [*DEFAULT_EXCLUDES, *(config.get("exclude_prefixes") or [])]
        suffixes = tuple(config.get("suffixes", DEFAULT_SUFFIXES))
        selected: list[str] = []
        for path in sorted(paths):
            if includes and not any(path.startswith(prefix) for prefix in includes):
                continue
            if any(path.startswith(prefix) for prefix in excludes):
                continue
            if not any(path.endswith(suffix) for suffix in suffixes):
                continue
            selected.append(path)
        max_files = int(config.get("max_files", 0) or 0)
        if max_files:
            selected = selected[:max_files]
        return selected

    def fetch(self, cursor: str | None) -> tuple[list[RawItem], str | None]:
        state: dict[str, str] = {}
        if cursor:
            try:
                state = json.loads(cursor)
            except json.JSONDecodeError:
                state = {}
        items: list[RawItem] = []
        for config in self.repos:
            repo = config["repo"]
            try:
                tree_sha, paths = self._tree(repo)
            except FetchError:
                continue
            if tree_sha and state.get(repo) == tree_sha:
                continue
            failed = False
            for path in self._select(paths, config):
                raw_url = f"{RAW_ROOT}/{repo}/HEAD/{quote(path, safe='/')}"
                try:
                    content = fetch_text(self.client, raw_url, sleep=self.sleep)
                except FetchError:
                    failed = True
                    continue
                if not content.strip():
                    continue
                name = path.rsplit("/", 1)[-1]
                stem = name.rsplit(".", 1)[0] if "." in name else name
                title_prefix = config.get("title_prefix")
                title = f"{title_prefix} {stem}" if title_prefix else stem
                items.append(
                    RawItem(
                        source_id=f"{repo}/{path}",
                        title=title,
                        content=content,
                        asset_type=config.get("asset_type", "post"),
                        url=f"https://github.com/{repo}/blob/HEAD/{quote(path, safe='/')}",
                        extra={"site": f"https://github.com/{repo}", "path": path},
                    )
                )
                if self.file_delay:
                    self.sleep(self.file_delay)
            if tree_sha and not failed:
                state[repo] = tree_sha
        return items, json.dumps(state)
