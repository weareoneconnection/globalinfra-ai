import asyncio

import httpx

import app.llm as llm
from app.llm import generate, is_llm_configured


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
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "")
    monkeypatch.setattr(llm.settings, "openai_compat_base_url", "http://local.test/v1")
    monkeypatch.setattr(llm.settings, "openai_compat_model", "qwen3:8b")

    real_client = httpx.AsyncClient
    captured = {}

    def handler(request):
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "connected"}}]})

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(llm.httpx, "AsyncClient", factory)
    assert asyncio.run(generate("system", "user")) == "connected"
    assert captured["authorization"] is None
