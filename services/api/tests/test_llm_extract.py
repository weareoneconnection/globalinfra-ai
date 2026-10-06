"""Tests for the V1.3 M3 + M4 LLM structured-extraction layer (Layer 3).

Covers the ``llm_extract`` module in isolation -- the deterministic mock-mode
fallback (returns ``None``), strict JSON parsing with per-field vocabulary
validation, entity grounding, M4 lifecycle-vocabulary validation and grounded
deadline parsing, real-mode extraction, and graceful degradation on upstream
failure / bad output -- plus the way ``build_intake_result`` consumes an injected
Layer-3 extraction (including the M4 per-field lifecycle/deadline fallback). The
async ``extract_fields_llm`` is exercised via ``asyncio.run`` so no
pytest-asyncio dependency is needed.

Real-mode tests monkeypatch ``app.llm_extract.generate`` and the shared
``settings`` singleton; mock mode is the default everywhere else (conftest sets
``LLM_MODE=mock``), so these never make a network call.
"""
import asyncio
import json

from app.config import settings
from app.intake import (
    COUNTRY_SIGNALS,
    ISSUE_SIGNALS,
    LIFECYCLE_SIGNALS,
    _DEFAULT_LIFECYCLE,
    build_intake_result,
)
from app.llm_extract import (
    RESPONSE_FORMAT,
    VALID_COUNTRY_CODES,
    VALID_ISSUE_KEYS,
    VALID_LIFECYCLE_IDS,
    _VALID_DEADLINE_UNITS,
    _parse,
    _parse_deadline,
    extract_fields_llm,
)

OWNER_TEXT = (
    "Owner notice to the Contractor: the temporary access road serving the "
    "Malaysia viaduct was damaged. Rectification is required within 48 hours. "
    "Refer to NCR-2026-311."
)


def _real_mode(monkeypatch, fake_generate):
    """Put llm_extract into real-model mode with a stubbed ``generate``."""
    monkeypatch.setattr(settings, "llm_mode", "openai")
    monkeypatch.setattr(settings, "openai_compat_api_key", "test-key")
    monkeypatch.setattr("app.llm_extract.generate", fake_generate)


# --- vocabulary is the single source of truth (read from intake tables) ------

def test_valid_vocab_tracks_intake_tables():
    assert VALID_COUNTRY_CODES == tuple(code for code, *_ in COUNTRY_SIGNALS)
    assert VALID_ISSUE_KEYS == tuple(label["en"] for _, label in ISSUE_SIGNALS)
    # M4: the lifecycle vocabulary is the deterministic signal ids + the default.
    assert VALID_LIFECYCLE_IDS == tuple(sid for sid, _ in LIFECYCLE_SIGNALS) + (_DEFAULT_LIFECYCLE,)


# --- parsing / validation / grounding ---------------------------------------

def test_parse_validates_and_grounds():
    raw = (
        '{"country": "MY", "issues": ["Owner notice", "Access road / temporary works"], '
        '"entities": ["NCR-2026-311", "Mars Base Alpha"]}'
    )
    out = _parse(raw, OWNER_TEXT)
    assert out["country"] == "MY"
    assert out["issues"] == ["Owner notice", "Access road / temporary works"]
    # NCR appears verbatim in the text; the hallucinated entity is dropped.
    assert out["entities"] == ["NCR-2026-311"]


def test_parse_tolerates_prose_and_code_fences():
    raw = 'Here you go:\n```json\n{"country": "MY", "issues": [], "entities": []}\n```'
    assert _parse(raw, OWNER_TEXT) == {
        "country": "MY", "issues": [], "entities": [], "lifecycle": None, "deadline": None,
    }


def test_parse_drops_out_of_vocab_country_and_issues():
    raw = '{"country": "FR", "issues": ["Owner notice", "Made Up Issue"], "entities": []}'
    out = _parse(raw, OWNER_TEXT)
    assert out["country"] is None          # FR is not in the routable set
    assert out["issues"] == ["Owner notice"]  # unknown issue label dropped
    assert out["entities"] == []


def test_parse_accepts_null_country():
    assert _parse('{"country": null, "issues": [], "entities": []}', OWNER_TEXT) == {
        "country": None, "issues": [], "entities": [], "lifecycle": None, "deadline": None,
    }


def test_parse_dedupes_issues():
    raw = '{"country": null, "issues": ["Owner notice", "Owner notice"], "entities": []}'
    assert _parse(raw, OWNER_TEXT)["issues"] == ["Owner notice"]


def test_parse_grounds_and_caps_entities():
    ids = [f"REF-{i}" for i in range(12)]
    text = " ".join(ids)
    raw = '{"country": null, "issues": [], "entities": %s}' % json.dumps(ids + ["GHOST-1"])
    out = _parse(raw, text)
    assert "GHOST-1" not in out["entities"]   # not in text -> dropped
    assert out["entities"] == ids[:8]         # capped at 8, same as the regex path


def test_parse_rejects_malformed_and_non_object():
    assert _parse("no json at all", OWNER_TEXT) is None
    assert _parse("", OWNER_TEXT) is None
    assert _parse("[1, 2, 3]", OWNER_TEXT) is None  # a JSON array, not an object


# --- extract_fields_llm: mock mode (default) --------------------------------

def test_mock_mode_returns_none():
    # conftest sets LLM_MODE=mock; the deterministic path must stay in control.
    assert asyncio.run(extract_fields_llm(OWNER_TEXT)) is None


# --- extract_fields_llm: real mode ------------------------------------------

def test_real_mode_extracts(monkeypatch):
    async def fake_generate(system, user, response_format=None):
        return '{"country": "MY", "issues": ["Owner notice"], "entities": ["NCR-2026-311"]}'

    _real_mode(monkeypatch, fake_generate)
    out = asyncio.run(extract_fields_llm(OWNER_TEXT))
    assert out == {
        "country": "MY", "issues": ["Owner notice"], "entities": ["NCR-2026-311"],
        "lifecycle": None, "deadline": None,
    }


def test_real_mode_falls_back_on_llm_error(monkeypatch):
    from app.llm import LLMError

    async def fake_generate(system, user, response_format=None):
        raise LLMError("upstream exploded")

    _real_mode(monkeypatch, fake_generate)
    assert asyncio.run(extract_fields_llm(OWNER_TEXT)) is None


def test_real_mode_falls_back_on_malformed(monkeypatch):
    async def fake_generate(system, user, response_format=None):
        return "sorry, I cannot help with that"

    _real_mode(monkeypatch, fake_generate)
    assert asyncio.run(extract_fields_llm(OWNER_TEXT)) is None


# --- build_intake_result consumes an injected extraction --------------------

def test_build_intake_result_uses_injected_extraction():
    # OWNER_TEXT mentions Malaysia; the injection overrides to Indonesia to prove
    # the injected extraction (not the keyword heuristic) is what drives routing.
    injected = {"country": "ID", "issues": ["Owner notice"], "entities": ["NCR-2026-999"]}
    result = build_intake_result(OWNER_TEXT, extraction=injected)
    assert result["extraction_method"] == "llm"
    assert result["country"] == "ID"
    assert result["country_label"] == {"en": "Indonesia", "zh": "印度尼西亚"}
    assert result["issues"] == [{"en": "Owner notice", "zh": "业主通知"}]
    assert result["entities"] == ["NCR-2026-999"]


def test_build_intake_result_injected_empty_issues_falls_to_case_type_label():
    injected = {"country": None, "issues": [], "entities": []}
    result = build_intake_result(OWNER_TEXT, extraction=injected)
    assert result["extraction_method"] == "llm"
    assert result["country"] is None
    # No issues extracted -> the case-type label stands in, same rule as Layer 1.
    assert result["issues"] == [result["case_type_label"]]


def test_build_intake_result_default_extraction_is_rules():
    result = build_intake_result(OWNER_TEXT)
    assert result["extraction_method"] == "rules"
    # Deterministic country detection still fires on the Malaysia keyword.
    assert result["country"] == "MY"
    assert "NCR-2026-311" in result["entities"]


# --- M4: lifecycle vocabulary validation ------------------------------------

def test_parse_extracts_valid_lifecycle():
    raw = '{"country": null, "issues": [], "entities": [], "lifecycle": "design", "deadline": null}'
    assert _parse(raw, OWNER_TEXT)["lifecycle"] == "design"


def test_parse_drops_out_of_vocab_lifecycle():
    raw = '{"country": null, "issues": [], "entities": [], "lifecycle": "banana", "deadline": null}'
    assert _parse(raw, OWNER_TEXT)["lifecycle"] is None


def test_parse_missing_lifecycle_is_none():
    # The three-key M3-shaped reply still parses; the new fields default to None.
    raw = '{"country": "MY", "issues": [], "entities": []}'
    out = _parse(raw, OWNER_TEXT)
    assert out["lifecycle"] is None and out["deadline"] is None


# --- M4: grounded deadline parsing ------------------------------------------

def test_parse_deadline_grounds_and_formats():
    # OWNER_TEXT says "within 48 hours" -- 48 appears verbatim, so it is kept.
    assert _parse_deadline({"amount": 48, "unit": "hours"}, OWNER_TEXT) == {
        "en": "48 hours", "zh": "48 小时",
    }


def test_parse_deadline_days_unit():
    assert _parse_deadline({"amount": 7, "unit": "days"}, "rectify within 7 days") == {
        "en": "7 days", "zh": "7 天",
    }


def test_parse_deadline_rejects_ungrounded_amount():
    # 99 is not written anywhere in the text -> dropped (regex fallback stands).
    assert _parse_deadline({"amount": 99, "unit": "hours"}, OWNER_TEXT) is None


def test_parse_deadline_rejects_bad_unit():
    assert _parse_deadline({"amount": 2, "unit": "weeks"}, "within 2 weeks") is None
    # "immediate" is deliberately unsupported here; the regex fallback owns it.
    assert _parse_deadline({"amount": None, "unit": "immediate"}, OWNER_TEXT) is None


def test_parse_deadline_rejects_nonpositive_and_nonint():
    assert _parse_deadline({"amount": 0, "unit": "hours"}, "0 hours") is None
    assert _parse_deadline({"amount": "48", "unit": "hours"}, OWNER_TEXT) is None
    assert _parse_deadline({"amount": True, "unit": "hours"}, OWNER_TEXT) is None  # bool is not a count
    assert _parse_deadline("not an object", OWNER_TEXT) is None


def test_parse_full_reply_with_lifecycle_and_deadline():
    raw = (
        '{"country": "MY", "issues": ["Owner notice"], "entities": ["NCR-2026-311"], '
        '"lifecycle": "construction", "deadline": {"amount": 48, "unit": "hours"}}'
    )
    assert _parse(raw, OWNER_TEXT) == {
        "country": "MY",
        "issues": ["Owner notice"],
        "entities": ["NCR-2026-311"],
        "lifecycle": "construction",
        "deadline": {"en": "48 hours", "zh": "48 小时"},
    }


# --- M4: real mode + build_intake_result injection --------------------------

def test_real_mode_extracts_lifecycle_and_deadline(monkeypatch):
    async def fake_generate(system, user, response_format=None):
        return (
            '{"country": "MY", "issues": [], "entities": [], '
            '"lifecycle": "design", "deadline": {"amount": 48, "unit": "hours"}}'
        )

    _real_mode(monkeypatch, fake_generate)
    out = asyncio.run(extract_fields_llm(OWNER_TEXT))
    assert out["lifecycle"] == "design"
    assert out["deadline"] == {"en": "48 hours", "zh": "48 小时"}


def test_build_intake_result_uses_injected_lifecycle_and_deadline():
    injected = {
        "country": None, "issues": [], "entities": [],
        "lifecycle": "handover", "deadline": {"en": "3 days", "zh": "3 天"},
    }
    result = build_intake_result(OWNER_TEXT, extraction=injected)
    assert result["extraction_method"] == "llm"
    assert result["lifecycle_stage"]["id"] == "handover"
    assert result["deadline"] == {"en": "3 days", "zh": "3 天"}


def test_build_intake_result_injected_empty_lifecycle_and_deadline_fall_back():
    # Model returned the extraction block but left lifecycle/deadline empty: each
    # falls back per-field to the deterministic heuristic rather than vanishing.
    injected = {"country": None, "issues": [], "entities": [], "lifecycle": None, "deadline": None}
    result = build_intake_result(OWNER_TEXT, extraction=injected)
    assert result["extraction_method"] == "llm"
    # OWNER_TEXT has no lifecycle keyword -> deterministic default "construction".
    assert result["lifecycle_stage"]["id"] == "construction"
    # OWNER_TEXT says "within 48 hours" -> the regex deadline still fires.
    assert result["deadline"] == {"en": "48 hours", "zh": "48 小时"}


def test_build_intake_result_invalid_injected_lifecycle_falls_back():
    # A lifecycle id that is not a real stage never reaches the result unchecked.
    injected = {"country": None, "issues": [], "entities": [], "lifecycle": "nonsense", "deadline": None}
    result = build_intake_result("Design drawing RFI raised for review.", extraction=injected)
    assert result["lifecycle_stage"]["id"] == "design"  # deterministic keyword hit


# --- M5: structured-output contract -----------------------------------------

def test_response_format_enums_track_vocabulary():
    # Every enum in the JSON schema is exactly the constrained vocabulary ``_parse``
    # validates against (plus null where the field is optional), so the schema sent
    # to the model can never drift from the parser.
    props = RESPONSE_FORMAT["json_schema"]["schema"]["properties"]
    assert props["country"]["enum"] == list(VALID_COUNTRY_CODES) + [None]
    assert props["issues"]["items"]["enum"] == list(VALID_ISSUE_KEYS)
    assert props["lifecycle"]["enum"] == list(VALID_LIFECYCLE_IDS) + [None]
    assert props["deadline"]["properties"]["unit"]["enum"] == list(_VALID_DEADLINE_UNITS)
    # strict is False: ``_parse``'s grounding guards are stricter than any schema.
    assert RESPONSE_FORMAT["json_schema"]["strict"] is False


def test_real_mode_requests_structured_output(monkeypatch):
    captured = {}

    async def fake_generate(system, user, response_format=None):
        captured["response_format"] = response_format
        return '{"country": "MY", "issues": [], "entities": [], "lifecycle": null, "deadline": null}'

    _real_mode(monkeypatch, fake_generate)
    out = asyncio.run(extract_fields_llm(OWNER_TEXT))
    assert out["country"] == "MY"
    # The structured-output contract was requested on the real call.
    assert captured["response_format"] is RESPONSE_FORMAT
