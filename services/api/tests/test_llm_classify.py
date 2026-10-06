"""Tests for the V1.3 M2 LLM classification layer (Layer 2).

Covers the ``llm_classify`` module in isolation -- the deterministic mock-mode
fallback, strict JSON parsing/vocabulary validation, real-mode override, and
graceful degradation on upstream failure / bad output -- plus the way
``build_intake_result`` consumes an injected Layer-2 classification. The async
``classify_text_llm`` is exercised via ``asyncio.run`` so no pytest-asyncio
dependency is needed.

Real-mode tests monkeypatch ``app.llm_classify.generate`` and the shared
``settings`` singleton; mock mode is the default everywhere else, so these never
make a network call.
"""
import asyncio

from app.classify import classify_text
from app.config import settings
from app.intake import build_intake_result
from app.llm_classify import (
    RESPONSE_FORMAT,
    VALID_CASE_TYPES,
    VALID_RISKS,
    _parse,
    classify_text_llm,
)
from app.workflow import SPECIALISTS_BY_CASE_TYPE

HSE_TEXT = "Worker near unprotected edge at elevated workface, no fall protection."
OWNER_TEXT = "Owner notice: access road damage, rectification required within 48 hours."


def _real_mode(monkeypatch, fake_generate):
    """Put llm_classify into real-model mode with a stubbed ``generate``."""
    monkeypatch.setattr(settings, "llm_mode", "openai")
    monkeypatch.setattr(settings, "openai_compat_api_key", "test-key")
    monkeypatch.setattr("app.llm_classify.generate", fake_generate)


# --- vocabulary is the single source of truth -------------------------------

def test_valid_case_types_track_specialist_routing():
    assert set(VALID_CASE_TYPES) == set(SPECIALISTS_BY_CASE_TYPE.keys())
    assert VALID_RISKS == ("CRITICAL", "HIGH", "MEDIUM", "LOW")


# --- parsing / validation ---------------------------------------------------

def test_parse_accepts_valid_json():
    assert _parse('{"case_type": "HSE", "risk": "CRITICAL"}') == {"type": "HSE", "risk": "CRITICAL"}


def test_parse_tolerates_prose_and_code_fences_and_lowercase_risk():
    raw = 'Here you go:\n```json\n{"case_type": "Quality", "risk": "medium"}\n```'
    assert _parse(raw) == {"type": "Quality", "risk": "MEDIUM"}


def test_parse_rejects_out_of_vocabulary_type():
    assert _parse('{"case_type": "Finance", "risk": "HIGH"}') is None


def test_parse_rejects_out_of_vocabulary_risk():
    assert _parse('{"case_type": "HSE", "risk": "EXTREME"}') is None


def test_parse_rejects_malformed_and_empty():
    assert _parse("not json at all") is None
    assert _parse("") is None
    assert _parse('{"case_type": "HSE"}') is None  # missing risk


# --- classify_text_llm: mock mode (default) ---------------------------------

def test_mock_mode_falls_back_to_rules():
    # conftest sets LLM_MODE=mock; mock mode must mirror classify_text exactly.
    out = asyncio.run(classify_text_llm(HSE_TEXT))
    assert out["method"] == "rules"
    rule = classify_text(HSE_TEXT)
    assert out["type"] == rule["type"] and out["risk"] == rule["risk"]


# --- classify_text_llm: real mode -------------------------------------------

def test_real_mode_uses_llm_result(monkeypatch):
    async def fake_generate(system, user, response_format=None):
        return '{"case_type": "Compliance", "risk": "HIGH"}'

    _real_mode(monkeypatch, fake_generate)
    out = asyncio.run(classify_text_llm("Some ambiguous letter about local permits."))
    assert out == {"type": "Compliance", "risk": "HIGH", "method": "llm"}


def test_real_mode_falls_back_on_llm_error(monkeypatch):
    from app.llm import LLMError

    async def fake_generate(system, user, response_format=None):
        raise LLMError("upstream exploded")

    _real_mode(monkeypatch, fake_generate)
    out = asyncio.run(classify_text_llm(HSE_TEXT))
    assert out["method"] == "rules"
    assert out["type"] == classify_text(HSE_TEXT)["type"]


def test_real_mode_falls_back_on_invalid_output(monkeypatch):
    async def fake_generate(system, user, response_format=None):
        return '{"case_type": "NotAThing", "risk": "HIGH"}'

    _real_mode(monkeypatch, fake_generate)
    out = asyncio.run(classify_text_llm(OWNER_TEXT))
    assert out["method"] == "rules"
    assert out["type"] == classify_text(OWNER_TEXT)["type"]


# --- build_intake_result consumes an injected classification ----------------

def test_build_intake_result_uses_injected_classification():
    injected = {"type": "HSE", "risk": "CRITICAL", "method": "llm"}
    # OWNER_TEXT would classify to Contract via rules; the injection overrides.
    result = build_intake_result(OWNER_TEXT, classification=injected)
    assert result["case_type"] == "HSE"
    assert result["risk"] == "CRITICAL"
    assert result["classification_method"] == "llm"
    assert result["recommended_agents"] == SPECIALISTS_BY_CASE_TYPE["HSE"]
    # LLM-classified cases get the higher confidence floor.
    assert result["confidence"] >= 0.75


def test_build_intake_result_default_is_rules():
    result = build_intake_result(OWNER_TEXT)
    assert result["classification_method"] == "rules"
    assert result["case_type"] == classify_text(OWNER_TEXT)["type"]


# --- M5: structured-output contract -----------------------------------------

def test_response_format_enums_track_vocabulary():
    # The JSON-schema enums must be exactly the constrained vocabularies ``_parse``
    # validates against, so the schema sent to the model can never drift from it.
    schema = RESPONSE_FORMAT["json_schema"]["schema"]
    assert schema["properties"]["case_type"]["enum"] == list(VALID_CASE_TYPES)
    assert schema["properties"]["risk"]["enum"] == list(VALID_RISKS)
    # Strict object with no extra keys, so a conforming endpoint returns exactly
    # the two fields ``_parse`` expects.
    assert RESPONSE_FORMAT["json_schema"]["strict"] is True
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"case_type", "risk"}


def test_real_mode_requests_structured_output(monkeypatch):
    captured = {}

    async def fake_generate(system, user, response_format=None):
        captured["response_format"] = response_format
        return '{"case_type": "HSE", "risk": "CRITICAL"}'

    _real_mode(monkeypatch, fake_generate)
    out = asyncio.run(classify_text_llm(HSE_TEXT))
    assert out == {"type": "HSE", "risk": "CRITICAL", "method": "llm"}
    # The structured-output contract was requested on the real call.
    assert captured["response_format"] is RESPONSE_FORMAT
