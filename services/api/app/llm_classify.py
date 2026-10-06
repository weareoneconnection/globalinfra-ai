"""Universal Intake Foundation (V1.3 Mission M2) -- LLM classification layer.

Layer 2 sits on top of the deterministic keyword rules in ``classify.py``
(Layer 1). When a real OpenAI-compatible model is configured it refines the
case-type / risk classification of free-text intake, constrained to exactly the
same label vocabulary the rules use so specialist routing via
``workflow.SPECIALISTS_BY_CASE_TYPE`` keeps working. When no model is configured
(the default offline / mock / CI posture) -- or whenever the model call fails,
returns malformed output, or returns an out-of-vocabulary label -- it falls back
to the Layer-1 rule result. Consequences, by design:

* The ``classify.py`` ``{"type", "risk"}`` contract is untouched; this module
  wraps it, it never edits or re-implements it.
* ``/cases/classify``, ``evals/run_eval.py`` and ``tests/test_classify.py`` keep
  calling ``classify_text`` directly and are entirely unaffected.
* With no API key (the default), the LLM path is inert and intake behaves
  byte-for-byte as it did in M1 -- so every M1 unit test and eval stays green
  with zero changes.

The return shape is the ``classify`` pair plus a ``method`` tag
(``"llm"``/``"rules"``) so callers can surface *how* a case was classified
without changing the authoritative ``{type, risk}`` routing values.
"""
from __future__ import annotations

import json
import re

from .classify import classify_text
from .config import settings
from .llm import LLMError, generate, is_llm_configured
from .workflow import SPECIALISTS_BY_CASE_TYPE

# Single source of truth for the routable vocabulary: the specialist routing
# table's keys are the canonical ``Case.type`` English labels. Constraining the
# model to these guarantees whatever it returns still routes to a real team.
VALID_CASE_TYPES: tuple[str, ...] = tuple(SPECIALISTS_BY_CASE_TYPE.keys())
VALID_RISKS: tuple[str, ...] = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

# Grab the first {...} block, tolerating stray prose / code fences around it.
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

# Structured-output contract (V1.3 M5): ask a capable OpenAI-compatible endpoint
# to return schema-valid JSON instead of free text we then regex a ``{...}`` out
# of. The enums are the SAME constrained vocabularies ``_parse`` validates
# against (built from the single-source-of-truth tuples above), so the schema and
# the parser can never drift. ``_parse`` still runs as the authoritative safety
# net: structured-output support varies across gateways (and is dropped+retried
# without it by ``llm.generate`` when unsupported), and a model may ignore the
# hint, so the reply is always re-validated regardless.
RESPONSE_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "case_classification",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["case_type", "risk"],
            "properties": {
                "case_type": {"type": "string", "enum": list(VALID_CASE_TYPES)},
                "risk": {"type": "string", "enum": list(VALID_RISKS)},
            },
        },
    },
}


def _system_prompt() -> str:
    types = "; ".join(VALID_CASE_TYPES)
    risks = ", ".join(VALID_RISKS)
    return (
        "You are a triage classifier for an overseas transportation-infrastructure "
        "project control tower. Classify the user's field observation / owner notice "
        "/ letter into exactly one case type and one risk level.\n"
        f"case_type MUST be exactly one of: {types}.\n"
        f"risk MUST be exactly one of: {risks}.\n"
        "Prefer safety (HSE) signals over administrative or contractual ones when "
        "both are present, and escalate risk for life-safety or imminent-collapse "
        'hazards. Respond with ONLY a compact JSON object of the form '
        '{"case_type": "...", "risk": "..."} -- no prose, no code fences.'
    )


def _parse(raw: str) -> dict | None:
    """Parse and validate the model's reply into a canonical ``{type, risk}``.

    Returns ``None`` (triggering the deterministic fallback) unless both fields
    are present and in-vocabulary, so a hallucinated label or malformed JSON can
    never produce an unroutable case.
    """
    match = _JSON_RE.search(raw or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    case_type = data.get("case_type")
    risk = str(data.get("risk", "")).strip().upper()
    if case_type not in VALID_CASE_TYPES or risk not in VALID_RISKS:
        return None
    return {"type": case_type, "risk": risk}


async def classify_text_llm(
    text: str, model_route: str | None = None, data_classification: str = "internal"
) -> dict:
    """Layer 2 classification with a deterministic Layer-1 fallback.

    Returns ``{"type", "risk", "method"}`` where ``method`` is ``"llm"`` when a
    configured model produced a valid in-vocabulary answer, else ``"rules"``.
    The ``{type, risk}`` pair is *always* valid for specialist routing.

    Unlike ``/cases/{id}/analyze`` and ``/i18n/translate`` (which surface an
    upstream model failure as a 502), classification degrades to the rule result
    instead of raising: the deterministic rules are a complete safety net for
    this step, and a genuinely broken model still surfaces downstream when
    ``analyze_case`` runs on the newly created Case.
    """
    rule = classify_text(text)
    if not is_llm_configured(model_route, data_classification):
        return {**rule, "method": "rules"}
    try:
        routing = {}
        if model_route is not None:
            routing["route"] = model_route
        if data_classification != "internal":
            routing["sensitivity"] = data_classification
        raw = await generate(_system_prompt(), text or "", response_format=RESPONSE_FORMAT, **routing)
    except LLMError:
        return {**rule, "method": "rules"}
    parsed = _parse(raw)
    if parsed is None:
        return {**rule, "method": "rules"}
    return {**parsed, "method": "llm"}
