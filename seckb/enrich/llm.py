from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Protocol

import httpx

from seckb.net import build_client

RETRY_STATUS = {429, 500, 502, 503, 504}


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    model: str

    def complete(self, prompt: str) -> str: ...


class OpenAICompatProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        client: httpx.Client | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1600,
        attempts: int = 3,
        extra_headers: dict[str, str] | None = None,
        thinking: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.client = client or build_client(timeout=180.0)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.attempts = attempts
        self.extra_headers = dict(extra_headers or {})
        self.thinking = thinking
        self.sleep = sleep

    def complete(self, prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        # DeepSeek 系模型默认开启 thinking 且 effort=high，富化是结构化抽取，
        # 思考 token 约占输出 75%，关掉可显著降本
        if self.thinking:
            payload["thinking"] = {"type": self.thinking}

        headers = {"Authorization": f"Bearer {self.api_key}", **self.extra_headers}
        for attempt in range(1, self.attempts + 1):
            response = self.client.post(url, json=payload, headers=headers)
            if response.status_code in RETRY_STATUS and attempt < self.attempts:
                self.sleep(0.5 * 2**attempt)
                continue
            if response.status_code >= 400:
                raise LLMError(f"LLM HTTP {response.status_code}: {response.text[:200]}")
            try:
                return response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError) as exc:
                raise LLMError(f"LLM 响应格式异常: {exc}") from exc
        raise LLMError("LLM 重试次数耗尽")


def build_provider(config: dict, *, client: httpx.Client | None = None) -> LLMProvider | None:
    provider_config = (config or {}).get("provider") or {}
    api_key = os.environ.get(provider_config.get("api_key_env", "DEEPSEEK_API_KEY"))
    if not api_key:
        return None
    return OpenAICompatProvider(
        base_url=provider_config.get("base_url", "https://api.deepseek.com/v1"),
        api_key=api_key,
        model=provider_config.get("model", "deepseek-chat"),
        client=client,
        temperature=float(provider_config.get("temperature", 0.2)),
        max_tokens=int(provider_config.get("max_tokens", 1600)),
        extra_headers={
            str(key): str(value)
            for key, value in (provider_config.get("headers") or {}).items()
        },
        thinking=provider_config.get("thinking") or None,
    )
