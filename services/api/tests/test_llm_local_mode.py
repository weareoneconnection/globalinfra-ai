import asyncio

import httpx

import pytest

import app.llm as llm
from app.llm import (
    LLMError,
    generate,
    is_llm_configured,
    reset_routing_trace,
    routing_status,
    routing_trace,
)


def test_local_mode_is_configured_without_an_api_key(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "local")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "")
    assert is_llm_configured() is True


def test_hosted_mode_still_requires_an_api_key(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "live")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "")
    assert is_llm_configured() is False


def test_local_generate_omits_authorization_header(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "local")
    monkeypatch.setattr(llm.settings, "local_llm_api_key", "")
    monkeypatch.setattr(llm.settings, "local_llm_base_url", "http://local.test/v1")
    monkeypatch.setattr(llm.settings, "local_llm_model", "qwen3:8b")

    real_client = httpx.AsyncClient
    captured = {}

    def handler(request):
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "connected"}}]})

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(llm.httpx, "AsyncClient", factory)
    async def run_traced():
        reset_routing_trace()
        result = await generate("system", "user")
        return result, routing_trace()

    result, trace = asyncio.run(run_traced())
    assert result == "connected"
    assert captured["authorization"] is None
    assert trace == [{"provider": "local", "model": "qwen3:8b", "status": "success"}]


def test_auto_route_falls_back_from_local_to_openai(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "auto")
    monkeypatch.setattr(llm.settings, "llm_preferred_provider", "local")
    monkeypatch.setattr(llm.settings, "llm_cloud_fallback_enabled", True)
    monkeypatch.setattr(llm.settings, "local_llm_base_url", "http://local.test/v1")
    monkeypatch.setattr(llm.settings, "local_llm_model", "qwen3:8b")
    monkeypatch.setattr(llm.settings, "local_llm_api_key", "")
    monkeypatch.setattr(llm.settings, "openai_compat_base_url", "https://cloud.test/v1")
    monkeypatch.setattr(llm.settings, "openai_compat_model", "gpt-test")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "secret")

    real_client = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append((str(request.url), request.headers.get("authorization")))
        if request.url.host == "local.test":
            return httpx.Response(503, json={"error": {"message": "offline"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "cloud fallback"}}]})

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(llm.httpx, "AsyncClient", factory)
    async def run_traced():
        reset_routing_trace()
        result = await generate("system", "user")
        return result, routing_trace()

    result, trace = asyncio.run(run_traced())
    assert result == "cloud fallback"
    assert ["local.test" in calls[0][0], "cloud.test" in calls[1][0]] == [True, True]
    assert calls[0][1] is None
    assert calls[1][1] == "Bearer secret"
    assert [item["status"] for item in trace] == ["failed", "success"]


def test_restricted_auto_route_never_falls_back_to_cloud(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "auto")
    monkeypatch.setattr(llm.settings, "local_llm_base_url", "http://local.test/v1")
    monkeypatch.setattr(llm.settings, "local_llm_model", "qwen3:8b")
    monkeypatch.setattr(llm.settings, "local_llm_api_key", "")
    monkeypatch.setattr(llm.settings, "openai_compat_base_url", "https://cloud.test/v1")
    monkeypatch.setattr(llm.settings, "openai_compat_model", "gpt-test")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "secret")

    real_client = httpx.AsyncClient
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return httpx.Response(503, json={"error": {"message": "offline"}})

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(llm.httpx, "AsyncClient", factory)
    with pytest.raises(LLMError):
        asyncio.run(generate("system", "user", route="auto", sensitivity="restricted"))
    assert hosts == ["local.test"]


def test_restricted_explicit_openai_route_is_rejected_before_http(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "auto")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "secret")
    with pytest.raises(LLMError, match="Restricted data"):
        asyncio.run(generate("system", "user", route="openai", sensitivity="restricted"))


def test_routing_status_never_exposes_keys(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "auto")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "super-secret")
    status = routing_status()
    assert status["data_policy"]["restricted"] == "local_only"
    assert "super-secret" not in str(status)
    assert "api_key" not in str(status)
