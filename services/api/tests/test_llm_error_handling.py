"""Regression test for the real-model failure path.

Reported symptom: with a real OpenAI-compatible model configured (``LLM_MODE``
!= mock and an API key set) but an invalid model id (e.g. ``"gpt-5.6 Luna"``,
which is not a real model and contains a space) or an unreachable endpoint,
clicking "Run AI Analysis" showed a raw ``Internal Server Error``.

Root cause: ``llm.generate`` called the upstream ``chat/completions`` API and
let httpx's own exception (``HTTPStatusError`` for a non-2xx response,
``RequestError``/``TimeoutException`` for a network failure) propagate
unchanged. Neither ``app.workflow.analyze_case`` nor the
``/cases/{id}/analyze`` and ``/i18n/translate`` routes in ``app.main`` had a
handler for it, so FastAPI's default exception middleware turned it into an
opaque 500 response with a leaked stack trace instead of a clean, actionable
error.

These tests pin the fix: any upstream transport/HTTP failure is normalized
into a single ``LLMError``, and the routes that can trigger a real model call
turn that into a clean ``502`` response instead of an unhandled crash.
"""
import asyncio

import httpx
import pytest

import app.llm as llm
import app.workflow as workflow
from app.llm import LLMError, generate


_RealAsyncClient = httpx.AsyncClient  # saved before any monkeypatch below replaces it


def _mock_async_client(handler):
    """Build a drop-in replacement for ``httpx.AsyncClient`` that never
    touches the network, routing requests through an in-memory transport
    instead (https://www.python-httpx.org/advanced/transports/#mock-transports)."""

    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return _RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def test_generate_wraps_an_invalid_model_response_as_llmerror(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "live")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "sk-test")
    # Mirrors the reported config: an invalid model id (contains a space).
    monkeypatch.setattr(llm.settings, "openai_compat_model", "gpt-5.6 Luna")

    def handler(request):
        return httpx.Response(400, json={"error": {"message": "The model `gpt-5.6 Luna` does not exist."}})

    monkeypatch.setattr(llm.httpx, "AsyncClient", _mock_async_client(handler))

    with pytest.raises(LLMError) as excinfo:
        asyncio.run(generate("system", "user"))
    assert "gpt-5.6 Luna" in str(excinfo.value)
    assert "400" in str(excinfo.value)


def test_generate_wraps_a_network_failure_as_llmerror(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "live")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "sk-test")

    def handler(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    monkeypatch.setattr(llm.httpx, "AsyncClient", _mock_async_client(handler))

    with pytest.raises(LLMError):
        asyncio.run(generate("system", "user"))


def test_analyze_endpoint_returns_a_clean_502_instead_of_crashing(client, monkeypatch):
    monkeypatch.setattr(workflow.settings, "llm_mode", "live")
    monkeypatch.setattr(workflow.settings, "openai_compat_api_key", "sk-test")

    async def failing_generate(system, user):
        raise LLMError("Upstream model call to 'gpt-5.6 Luna' failed with HTTP 400: model does not exist")

    monkeypatch.setattr(workflow, "generate", failing_generate)

    r = client.post("/cases/CASE-2026-0182/analyze")
    assert r.status_code == 502
    assert "gpt-5.6 Luna" in r.text


def test_translate_endpoint_returns_a_clean_502_instead_of_crashing(client, monkeypatch):
    import app.main as main

    async def failing_translate(text, target_lang, source_lang="en"):
        raise LLMError("Upstream model call to 'gpt-5.6 Luna' failed with HTTP 400: model does not exist")

    monkeypatch.setattr(main, "translate", failing_translate)

    r = client.post("/i18n/translate", json={"text": "hello", "target_lang": "zh"})
    assert r.status_code == 502
    assert "gpt-5.6 Luna" in r.text
