"""Regression test for real calls to newer "reasoning" model families.

Reported symptom: with ``LLM_MODE=live``, a real API key, and
``OPENAI_COMPAT_MODEL=gpt-5.5`` (a real, reachable model — verified directly
against ``https://api.openai.com/v1/chat/completions`` during manual
retesting), every single call to ``generate``/``translate`` failed with a
clean ``LLMError``/502, never a 200:

    Upstream model call to 'gpt-5.5' failed with HTTP 400: {
      "error": {
        "message": "Unsupported value: 'temperature' does not support 0.1
          with this model. Only the default (1) value is supported.",
        "type": "invalid_request_error",
        "param": "temperature",
        "code": "unsupported_value"
      }
    }

Root cause: ``llm.generate`` always sent a hardcoded ``"temperature": 0.1``
to bias real-model output towards determinism. Older chat-completion models
accept that, but the newer ``gpt-5.x`` reasoning-style model family only
supports the default temperature (``1``) and rejects any explicit value
with a 400 ``unsupported_value`` error — so a correctly configured,
reachable, authenticated model was still unusable end to end.

The fix: on exactly that 400 ``unsupported_value``/``temperature`` response,
retry once without the ``temperature`` field instead of surfacing it as a
hard failure. Other 400s (bad model id, bad auth, any other unsupported
param) still raise ``LLMError`` as before — this is not a blanket retry.
"""
import asyncio

import httpx
import pytest

import app.llm as llm
from app.llm import LLMError, generate

_RealAsyncClient = httpx.AsyncClient  # saved before any monkeypatch replaces it


def _mock_async_client(handler):
    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return _RealAsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def test_generate_retries_without_temperature_when_model_rejects_it(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "live")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "sk-test")
    monkeypatch.setattr(llm.settings, "openai_compat_model", "gpt-5.5")

    calls = []

    def handler(request):
        import json

        body = json.loads(request.content)
        calls.append(body)
        if "temperature" in body:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Unsupported value: 'temperature' does not support 0.1 "
                        "with this model. Only the default (1) value is supported.",
                        "type": "invalid_request_error",
                        "param": "temperature",
                        "code": "unsupported_value",
                    }
                },
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Hello!"}}]},
        )

    monkeypatch.setattr(llm.httpx, "AsyncClient", _mock_async_client(handler))

    result = asyncio.run(generate("system", "user"))
    assert result == "Hello!"
    # First attempt included the deterministic temperature, the retry dropped it.
    assert len(calls) == 2
    assert "temperature" in calls[0]
    assert "temperature" not in calls[1]


def test_generate_does_not_retry_other_400s(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "live")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "sk-test")
    monkeypatch.setattr(llm.settings, "openai_compat_model", "gpt-5.6 Luna")

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"error": {"message": "The model `gpt-5.6 Luna` does not exist."}})

    monkeypatch.setattr(llm.httpx, "AsyncClient", _mock_async_client(handler))

    with pytest.raises(LLMError):
        asyncio.run(generate("system", "user"))
    assert len(calls) == 1
