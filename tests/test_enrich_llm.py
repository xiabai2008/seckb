import httpx
import pytest

from seckb.enrich.llm import LLMError, OpenAICompatProvider, build_provider
from seckb.net import build_client


def test_complete_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"summary": "ok"}'}}]}
        )

    client = build_client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatProvider(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="test-model",
        client=client,
        sleep=lambda _: None,
    )
    assert provider.complete("hi") == '{"summary": "ok"}'


def test_complete_retries_429():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})

    client = build_client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatProvider(
        base_url="https://api.example.com/v1",
        api_key="k",
        model="m",
        client=client,
        sleep=lambda _: None,
    )
    assert provider.complete("hi") == "done"
    assert len(calls) == 2


def test_complete_400_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    client = build_client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatProvider(
        base_url="https://api.example.com/v1",
        api_key="k",
        model="m",
        client=client,
        sleep=lambda _: None,
    )
    with pytest.raises(LLMError):
        provider.complete("hi")


def test_build_provider_without_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = {"provider": {"api_key_env": "DEEPSEEK_API_KEY"}}
    assert build_provider(config) is None


def test_build_provider_with_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    config = {
        "provider": {
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key_env": "DEEPSEEK_API_KEY",
        }
    }
    provider = build_provider(config)
    assert provider is not None
    assert provider.model == "deepseek-chat"


def test_complete_sends_extra_headers():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-opencode-session"] == "seckb-enrich"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = build_client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatProvider(
        base_url="https://opencode.ai/zen/go/v1",
        api_key="k",
        model="m",
        client=client,
        extra_headers={"x-opencode-session": "seckb-enrich"},
        sleep=lambda _: None,
    )
    assert provider.complete("hi") == "ok"


def test_build_provider_passes_headers(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "secret")
    config = {
        "provider": {
            "api_key_env": "OPENCODE_API_KEY",
            "headers": {"x-opencode-session": "seckb-enrich"},
        }
    }
    provider = build_provider(config)
    assert provider is not None
    assert provider.extra_headers == {"x-opencode-session": "seckb-enrich"}


def test_default_client_has_generous_timeout():
    provider = OpenAICompatProvider(base_url="https://example.com/v1", api_key="k", model="m")
    assert provider.client.timeout.read == 180.0
