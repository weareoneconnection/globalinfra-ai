"""Model-composed reply letter for the governed ``document.generate`` tool.

When a model is configured, the approved draft is written by the model from
the incoming letter, the specialist findings and the cited evidence, instead
of the fixed template in ``governed_execution``. Guardrails:

* It runs only after every human approval (the execute endpoint calls it), and
  the result still goes through the same content-addressed artifact, receipt
  and independent verification; it is never sent anywhere.
* The prompt forbids commitments on cost, time or liability and any fact not
  in the letter or the evidence; unknown details become ``[●]`` placeholders.
* Every square-bracket citation must be one of the action's evidence refs (or
  a placeholder), and at least one ref must be cited. Otherwise the draft is
  discarded and the deterministic template is used.
* Restricted intakes are composed only on the local model route.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .llm import LLMError, generate, is_llm_configured
from .models import Action, AgentRun, Case, Evidence, IngestionReceipt, IntakeSubmission

MAX_SOURCE_CHARS = 6000
MAX_REPLY_CHARS = 6000
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")
_PLACEHOLDER_RE = re.compile(r"^[●•\s.…_—-]+$")

REPLY_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "reply_letter",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["en", "zh"],
            "properties": {"en": {"type": "string"}, "zh": {"type": "string"}},
        },
    },
}

SYSTEM_PROMPT = (
    "You draft formal reply letters for an overseas infrastructure project team. The incoming letter "
    "was addressed to the project team; write the team's reply to its sender (use the sender's and "
    "recipient's names exactly as they appear in the letter, otherwise [●]).\n"
    "Rules:\n"
    "- Use only facts stated in the incoming letter, the specialist findings and the evidence. Never "
    "invent dates, quantities, amounts, clause numbers or names; write [●] for anything unknown.\n"
    "- Do not accept or reject liability, cost or time. Acknowledge receipt, state that the matter is "
    "under review, request any missing substantiation the evidence calls for, and reserve the "
    "project's contractual rights.\n"
    "- Cite the evidence that supports each position with its reference in square brackets exactly as "
    "given, e.g. [CTR-A / Clause 13]. Cite only the references listed.\n"
    "- Keep it under 300 words per language. Return JSON with the English letter in `en` and a "
    "faithful Simplified Chinese version in `zh`."
)


def _classification(db: Session, case_id: str) -> str:
    receipt = db.scalar(select(IngestionReceipt).where(IngestionReceipt.target_id == case_id)
                        .order_by(IngestionReceipt.created_at.desc()))
    return str((receipt.lineage or {}).get("data_classification") or "internal") if receipt else "internal"


def _user_note(db: Session, case_id: str) -> str:
    receipt = db.scalar(select(IngestionReceipt).where(IngestionReceipt.target_id == case_id)
                        .order_by(IngestionReceipt.created_at.desc()))
    return str((receipt.lineage or {}).get("user_note") or "") if receipt else ""


def _source_text(db: Session, case: Case) -> str:
    submission = db.scalar(select(IntakeSubmission).where(IntakeSubmission.case_id == case.id)
                           .order_by(IntakeSubmission.id.desc()))
    text = submission.parsed_text if submission and submission.parsed_text else (case.description or {}).get("en", "")
    return text[:MAX_SOURCE_CHARS]


def validate_reply(body: dict, refs: set[str]) -> bool:
    """Both languages present and every citation is a known ref or a placeholder."""
    if not isinstance(body, dict):
        return False
    for lang in ("en", "zh"):
        text = body.get(lang)
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_REPLY_CHARS:
            return False
        brackets = [item.strip() for item in _BRACKET_RE.findall(text)]
        cited = [item for item in brackets if not _PLACEHOLDER_RE.match(item)]
        if not cited or not set(cited) <= refs:
            return False
    return True


def _parse(raw: str, refs: set[str]) -> dict | None:
    match = _JSON_RE.search(raw or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    body = {"en": str(data.get("en") or "").strip(), "zh": str(data.get("zh") or "").strip()} if isinstance(data, dict) else None
    return body if body and validate_reply(body, refs) else None


async def compose_reply(db: Session, action: Action) -> dict | None:
    """Return a validated ``{"en", "zh"}`` reply body, or None to use the template."""
    case = db.get(Case, action.case_id)
    if case is None:
        return None
    classification = _classification(db, case.id)
    route = "local" if classification == "restricted" else None
    try:
        if not is_llm_configured(route, classification):
            return None
    except LLMError:
        return None
    evidence = [row for row in db.scalars(select(Evidence).where(Evidence.case_id == case.id))
                if row.source_ref in set(action.evidence_refs or [])]
    if not evidence:
        return None
    refs = {row.source_ref for row in evidence}
    findings = "\n".join(
        f"- {(run.agent or {}).get('en', '')}: {(run.summary or {}).get('en', '')}"
        for run in db.scalars(select(AgentRun).where(AgentRun.case_id == case.id).order_by(AgentRun.id))
    )
    sources = "\n".join(
        f"[{row.source_ref}] {(row.title or {}).get('en', '')}: {(row.excerpt or {}).get('en', '')}"
        for row in evidence
    )
    note = _user_note(db, case.id)
    user = (
        f"Incoming letter:\n{_source_text(db, case)}\n\n"
        f"Specialist findings:\n{findings}\n\n"
        f"Evidence you may cite (only these references):\n{sources}"
        + (f"\n\nThe user's request about this letter (an instruction, not a fact): {note}" if note else "")
    )
    try:
        raw = await generate(SYSTEM_PROMPT, user, response_format=REPLY_FORMAT, route=route, sensitivity=classification)
    except LLMError:
        return None
    return _parse(raw, refs)
