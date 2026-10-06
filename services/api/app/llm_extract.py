"""Universal Intake Foundation (V1.3 Missions M3 + M4) -- LLM structured-extraction layer.

Layer 3 sits on top of the deterministic keyword/regex enrichment in
``intake.py``: ``country`` for project routing, ``issues`` for display, the
reference ``entities`` (M3), and -- added in M4 -- the project ``lifecycle``
stage and the response ``deadline``. When a real OpenAI-compatible model is
configured it extracts all of these structured fields in **one** call,
**constrained** to exactly the same vocabularies the deterministic heuristics use
(so a Case still routes to a project, every issue still has a bilingual display
label, and the lifecycle id always resolves to a real stage) and **grounded**
against the source text (so a hallucinated reference identifier -- or a deadline
number that was never written down -- can never enter a Case). When no model is
configured (the default offline / mock / CI posture) -- or whenever the model
call fails or returns malformed output -- it returns ``None`` and
``intake.build_intake_result`` keeps its deterministic extraction, byte-for-byte
as in M1/M2.

Design mirrors the M2 classification layer (``llm_classify``):

* The deterministic heuristics in ``intake.py`` are untouched; this module wraps
  them, it never edits or re-implements them. When it returns ``None`` (the
  default) ``build_intake_result`` computes every field exactly as before, so all
  M1/M2 unit tests and evals stay green offline with zero changes.
* The constrained vocabularies are a single source of truth: the country codes
  and the English issue labels are read straight from ``intake``'s
  ``COUNTRY_SIGNALS`` / ``ISSUE_SIGNALS`` tables, so the model can only ever
  return a value that still routes / still has a bilingual display label.
* Entities are grounded: only strings that appear verbatim (case-insensitively)
  in the source text survive, so the model can surface references the regex
  missed without being able to invent ones that are not there.
* Unlike ``/cases/{id}/analyze`` and ``/i18n/translate`` (which surface an
  upstream model failure as a 502), extraction degrades silently to the
  deterministic result rather than raising -- the heuristics are a complete
  safety net for this step, and a genuinely broken model still surfaces
  downstream when ``analyze_case`` runs on the newly created Case.
"""
from __future__ import annotations

import json
import re

from .config import settings
from .intake import (
    COUNTRY_SIGNALS,
    ISSUE_SIGNALS,
    LIFECYCLE_SIGNALS,
    _DEFAULT_LIFECYCLE,
    format_deadline,
)
from .llm import LLMError, generate, is_llm_configured

# Single source of truth for the constrained vocabularies -- read from the same
# deterministic tables intake.py routes / labels on, so anything the model
# returns still attaches to a project and still has a bilingual display label.
VALID_COUNTRY_CODES: tuple[str, ...] = tuple(code for code, *_ in COUNTRY_SIGNALS)
VALID_ISSUE_KEYS: tuple[str, ...] = tuple(label["en"] for _, label in ISSUE_SIGNALS)
# Lifecycle stage ids the model may choose from (M4): the deterministic signal
# ids plus the default stage, read from intake so both paths share one vocabulary
# and every id is guaranteed to resolve to a real, bilingual lifecycle stage.
VALID_LIFECYCLE_IDS: tuple[str, ...] = tuple(stage_id for stage_id, _ in LIFECYCLE_SIGNALS) + (_DEFAULT_LIFECYCLE,)

# Same cap intake._detect_entities applies, so the LLM and regex paths produce
# entity lists of the same bounded size.
_MAX_ENTITIES = 8

# Deadline units the model may return (M4). "immediate" / unquantified deadlines
# deliberately stay on the deterministic regex fallback: the LLM's value-add here
# is picking the *right* number among several, which only applies to quantities.
_VALID_DEADLINE_UNITS = ("hours", "days")

# Grab the first {...} block, tolerating stray prose / code fences around it.
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

# Structured-output contract (V1.3 M5): ask a capable OpenAI-compatible endpoint
# to return schema-valid JSON for the five extraction keys instead of free text we
# regex a ``{...}`` out of. The country / issue / lifecycle / deadline-unit enums
# are the SAME constrained vocabularies ``_parse`` validates against, so schema and
# parser can never drift. ``strict`` is deliberately False: ``_parse`` remains the
# authoritative safety net -- its guards are *stricter* than any JSON schema can
# express (entities must appear verbatim in the text; a deadline amount must appear
# verbatim; out-of-vocabulary fields degrade to their valid subset rather than
# rejecting the whole reply), and ``llm.generate`` drops+retries without the field
# on gateways that don't support structured outputs, so the reply is always
# re-validated regardless.
RESPONSE_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "intake_extraction",
        "strict": False,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["country", "issues", "entities", "lifecycle", "deadline"],
            "properties": {
                "country": {"type": ["string", "null"], "enum": list(VALID_COUNTRY_CODES) + [None]},
                "issues": {"type": "array", "items": {"type": "string", "enum": list(VALID_ISSUE_KEYS)}},
                "entities": {"type": "array", "items": {"type": "string"}},
                "lifecycle": {"type": ["string", "null"], "enum": list(VALID_LIFECYCLE_IDS) + [None]},
                "deadline": {
                    "type": ["object", "null"],
                    "additionalProperties": False,
                    "required": ["amount", "unit"],
                    "properties": {
                        "amount": {"type": "integer"},
                        "unit": {"type": "string", "enum": list(_VALID_DEADLINE_UNITS)},
                    },
                },
            },
        },
    },
}


def _system_prompt() -> str:
    countries = ", ".join(VALID_COUNTRY_CODES)
    issues = "; ".join(VALID_ISSUE_KEYS)
    lifecycles = ", ".join(VALID_LIFECYCLE_IDS)
    return (
        "You extract structured routing fields from a transportation-infrastructure "
        "field observation / owner notice / letter. Return a compact JSON object with "
        "exactly five keys:\n"
        f'"country": the ISO 3166-1 alpha-2 code of the country the work is in, chosen '
        f"ONLY from [{countries}], or null if none of them clearly applies.\n"
        f'"issues": an array (possibly empty) of the problems present, each chosen '
        f"EXACTLY from this list: {issues}.\n"
        '"entities": an array (possibly empty) of reference identifiers (NCR / contract '
        "clause / drawing / variation numbers) and named parties or locations that "
        "appear verbatim in the text.\n"
        f'"lifecycle": the project lifecycle stage the matter concerns, chosen ONLY '
        f"from [{lifecycles}], or null if unclear.\n"
        '"deadline": the response deadline as an object {"amount": <positive integer>, '
        '"unit": "hours" or "days"} using the number written verbatim in the text, or '
        "null if no explicit hour/day deadline is stated.\n"
        "Respond with ONLY the JSON object -- no prose, no code fences."
    )


def _parse_deadline(raw: object, text: str) -> dict | None:
    """Validate + ground a structured ``{"amount", "unit"}`` deadline into the
    shared bilingual label, or ``None`` so the deterministic regex fallback stands.

    Grounding mirrors the entity guard: the chosen amount must appear verbatim in
    the source text, so the model can pick the *right* number among several but can
    never invent a deadline that is not written down. ``bool`` is rejected
    explicitly (it is an ``int`` subclass)."""
    if not isinstance(raw, dict):
        return None
    unit = raw.get("unit")
    amount = raw.get("amount")
    if unit not in _VALID_DEADLINE_UNITS or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        return None
    if str(amount) not in (text or ""):
        return None
    return format_deadline(amount, unit)


def _parse(raw: str, text: str) -> dict | None:
    """Parse + validate + ground the model reply into
    ``{"country", "issues", "entities", "lifecycle", "deadline"}``.

    Returns ``None`` (triggering the deterministic fallback) only when the reply
    is not a usable JSON object. Individual fields are *sanitised* rather than
    rejecting the whole reply: an out-of-vocabulary country / lifecycle becomes
    ``None``, out-of-vocabulary issues are dropped, entities not found verbatim in
    the source text are dropped, and an unquantified / ungrounded deadline becomes
    ``None`` (the regex fallback then stands) -- so a partially-hallucinated reply
    degrades to its valid subset instead of poisoning a Case.
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

    country = data.get("country")
    if country not in VALID_COUNTRY_CODES:
        country = None

    issues: list[str] = []
    raw_issues = data.get("issues")
    if isinstance(raw_issues, list):
        for item in raw_issues:
            if item in VALID_ISSUE_KEYS and item not in issues:
                issues.append(item)

    entities: list[str] = []
    raw_entities = data.get("entities")
    lowered = (text or "").lower()
    if isinstance(raw_entities, list):
        for item in raw_entities:
            if not isinstance(item, str):
                continue
            item = item.strip()
            # Grounding guard: keep only references that really occur in the text.
            if item and item.lower() in lowered and item not in entities:
                entities.append(item)
            if len(entities) >= _MAX_ENTITIES:
                break

    lifecycle = data.get("lifecycle")
    if lifecycle not in VALID_LIFECYCLE_IDS:
        lifecycle = None

    deadline = _parse_deadline(data.get("deadline"), text)

    return {
        "country": country,
        "issues": issues,
        "entities": entities,
        "lifecycle": lifecycle,
        "deadline": deadline,
    }


async def extract_fields_llm(text: str) -> dict | None:
    """Layer 3 structured extraction, or ``None`` for the deterministic path.

    Returns ``{"country", "issues", "entities", "lifecycle", "deadline"}`` when a
    configured model produced a usable reply, else ``None`` so
    ``build_intake_result`` keeps its deterministic Layer-1 extraction. Never
    raises on an upstream failure -- the heuristics are a complete fallback for
    this step.
    """
    if not is_llm_configured():
        return None
    try:
        raw = await generate(_system_prompt(), text or "", response_format=RESPONSE_FORMAT)
    except LLMError:
        return None
    return _parse(raw, text or "")
