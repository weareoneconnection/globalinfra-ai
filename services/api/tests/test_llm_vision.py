"""Multimodal routing must preserve drawing evidence and fail closed."""

import asyncio
import json

import httpx
import pytest

import app.llm as llm
from app.llm import LLMError, generate_vision


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _mock_async_client(handler):
    def factory(*args, **kwargs):
        kwargs.pop("timeout", None)
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def test_generate_vision_sends_inline_image_and_schema(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "live")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "sk-test")
    monkeypatch.setattr(llm.settings, "openai_compat_model", "vision-test")
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok":true}'}}]}
        )

    monkeypatch.setattr(llm.httpx, "AsyncClient", _mock_async_client(handler))
    schema = {"type": "json_schema", "json_schema": {"name": "drawing", "schema": {}}}
    result = asyncio.run(
        generate_vision(
            "Only report visible drawing evidence.",
            "Extract title block fields.",
            [("image/png", b"\x89PNG\r\n\x1a\n")],
            response_format=schema,
        )
    )

    assert result == '{"ok":true}'
    assert calls[0]["response_format"] == schema
    user_content = calls[0]["messages"][1]["content"]
    assert user_content[0] == {"type": "text", "text": "Extract title block fields."}
    assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert user_content[1]["image_url"]["detail"] == "high"


def test_generate_vision_has_no_fabricated_mock_fallback(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "mock")
    with pytest.raises(LLMError, match="No eligible multimodal"):
        asyncio.run(
            generate_vision("system", "user", [("image/jpeg", b"not-a-real-image")])
        )


def test_generate_vision_rejects_unsupported_media_before_network(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_mode", "live")
    monkeypatch.setattr(llm.settings, "openai_compat_api_key", "sk-test")
    with pytest.raises(LLMError, match="Unsupported multimodal image type"):
        asyncio.run(generate_vision("system", "user", [("image/tiff", b"II")]))
