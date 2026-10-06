"""Tests for the V1.3 M5 structured-output hardening in ``llm.generate``.

The two LLM layers (M2 classification, M3/M4 extraction) now ask the configured
OpenAI-compatible endpoint for schema-valid JSON via a ``response_format`` field.
Not every real gateway/model implements structured outputs, so -- exactly like
the existing ``temperature`` handling for reasoning-style models -- ``generate``
drops the ``response_format`` field and retries once on the specific 400 that
names it, and leaves every other 400 raising as before. These tests drive the
real HTTP path with a mocked transport (no network), covering:

* the field is sent on the wire when a caller requests it;
* a 400 rejecting ``response_format`` triggers a single retry without it;
* both tuning fields can be dropped in sequence when a model rejects both;
* an unrelated 400 still surfaces as an ``LLMError`` (not a blanket retry).
"""
import asyncio
import json

import httpx
import pytest

import app.llm as llm
from app.llm import LLMError, generate, reset_routing_trace, routing_trace

_RealAsyncClient = httpx.AsyncClient  # saved before any monkeypatch replaces it

_SCHEMA = {"type": "json_schema", "json_schema": {"name": "t", "strict": True, "schema": {}}}


def _mock_async_client(handler):
    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return _RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def _real_model(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "live")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "sk-test")
    monkeypatch.setattr(llm.settings, "openai_compat_model", "gpt-5.6")


def _reject(param):
    return httpx.Response(
        400,
        json={"error": {"message": f"Unsupported parameter: {param}.",
                        "type": "invalid_request_error", "param": param,
                        "code": "unsupported_value" if param == "temperature" else "unsupported_parameter"}},
    )


def test_generate_sends_response_format_when_supported(monkeypatch):
    _real_model(monkeypatch)
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr(llm.httpx, "AsyncClient", _mock_async_client(handler))

    result = asyncio.run(generate("system", "user", response_format=_SCHEMA))
    assert result == '{"ok": true}'
    assert len(calls) == 1
    assert calls[0]["response_format"] == _SCHEMA


def test_generate_retries_without_response_format_when_rejected(monkeypatch):
    _real_model(monkeypatch)
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if "response_format" in body:
            return _reject("response_format")
        return httpx.Response(200, json={"choices": [{"message": {"content": "plain text"}}]})

    monkeypatch.setattr(llm.httpx, "AsyncClient", _mock_async_client(handler))

    result = asyncio.run(generate("system", "user", response_format=_SCHEMA))
    assert result == "plain text"
    # First attempt carried the structured-output field, the retry dropped it.
    assert len(calls) == 2
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]
    # Dropping response_format must not collaterally drop the temperature field.
    assert "temperature" in calls[1]


def test_generate_drops_temperature_then_response_format(monkeypatch):
    # A model that rejects BOTH tuning fields should still succeed: each 400 drops
    # exactly the named field and retries, so the loop converges in three calls.
    _real_model(monkeypatch)
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if "temperature" in body:
            return _reject("temperature")
        if "response_format" in body:
            return _reject("response_format")
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})

    monkeypatch.setattr(llm.httpx, "AsyncClient", _mock_async_client(handler))

    result = asyncio.run(generate("system", "user", response_format=_SCHEMA))
    assert result == "done"
    assert len(calls) == 3
    assert "temperature" in calls[0] and "response_format" in calls[0]
    assert "temperature" not in calls[1]  # temperature dropped first
    assert "response_format" not in calls[2]  # then response_format


def test_routing_trace_survives_concurrent_gather(monkeypatch):
    """M6 guard: when two ``generate`` calls run concurrently under
    ``asyncio.gather`` (as the intake classify + extract layers now do), both
    route records must remain visible to the parent's ``routing_trace()``.

    ``gather`` runs each coroutine in its own copied context, so ``_record_route``
    must mutate the trace list in place; a copy-then-``set`` would strand each
    record in a child context and the parent would see an empty trace.
    """
    _real_model(monkeypatch)

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm.httpx, "AsyncClient", _mock_async_client(handler))

    async def drive():
        reset_routing_trace()
        await asyncio.gather(
            generate("system", "classify"),
            generate("system", "extract"),
        )
        return routing_trace()

    trace = asyncio.run(drive())
    assert len(trace) == 2
    assert all(entry["status"] == "success" for entry in trace)


def test_generate_does_not_retry_unrelated_400_with_response_format(monkeypatch):
    _real_model(monkeypatch)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"error": {"message": "The model does not exist."}})

    monkeypatch.setattr(llm.httpx, "AsyncClient", _mock_async_client(handler))

    with pytest.raises(LLMError):
        asyncio.run(generate("system", "user", response_format=_SCHEMA))
    assert len(calls) == 1  # no blanket retry
