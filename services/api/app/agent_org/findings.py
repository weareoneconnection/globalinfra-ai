"""Structured specialist findings.

A finding is one agent's conclusion for one case: a claim, the evidence it
rests on, its status (SUPPORTED, GAP or NEEDS_INPUT), the gaps it found,
recommended actions with an owner role, and any question for a human.

Model-written findings are validated: every cited reference must be one the
agent's own knowledge.search returned, and a SUPPORTED finding must cite at
least one confident source. Anything else is downgraded to a GAP, so a
model can never turn weak or foreign evidence into a conclusion.
"""
from __future__ import annotations

import json
import re

from ..i18n import bi
from ..llm import LLMError, generate
from .cards import AgentCard
from .tools import CONFIDENT_RELEVANCE, ToolResult

STATUSES = ("SUPPORTED", "GAP", "NEEDS_INPUT")


def _norm(ref: str) -> str:
    """Compare references ignoring spacing and case ("CTR-A/Clause13" == "CTR-A / Clause 13")."""
    return "".join(ref.split()).lower()


def _bi(value) -> dict:
    if isinstance(value, dict):
        en = str(value.get("en") or "").strip()
        return bi(en, str(value.get("zh") or "").strip() or en)
    return bi(str(value or "").strip())


def _knowledge(results: list[ToolResult]) -> list:
    return next((r.hits for r in results if r.tool == "knowledge.search"), [])


def finding_summary(finding: dict) -> dict:
    """The one-paragraph text shown as the agent's run summary."""
    return finding["claim"]


def deterministic_finding(card: AgentCard, results: list[ToolResult], answers: list[str]) -> dict:
    hits = _knowledge(results)
    refs = [doc.source_ref for _, doc in hits]
    focus = card.focus
    blocking = [r for r in results if r.tool == "cost.estimate" and not r.ok]
    context_notes = [r.summary for r in results if r.tool != "knowledge.search" and r.ok]
    if hits and hits[0][0] >= CONFIDENT_RELEVANCE and not blocking:
        top_score, top_doc = hits[0]
        claim = bi(
            f"Reviewed {len(hits)} evidence item(s) for {focus['en']}; top reference {top_doc.source_ref} — "
            f"\"{top_doc.summary.get('en', '')}\" (similarity {top_score:.2f}).",
            f"针对{focus['zh']}核查了 {len(hits)} 条证据；首要引用 {top_doc.source_ref} ——"
            f"“{top_doc.summary.get('zh', '')}”（相关度 {top_score:.2f}）。",
        )
        status, gaps, questions = "SUPPORTED", [], []
        confidence = round(min(0.97, 0.6 + top_score), 3)
    else:
        if blocking:
            claim = bi(
                f"Evidence gap for {focus['en']}: {blocking[0].summary['en']}",
                f"{focus['zh']}存在证据缺口：{blocking[0].summary['zh']}",
            )
        elif hits:
            claim = bi(
                f"Only limited evidence for {focus['en']} was found ({', '.join(refs)}, similarity {hits[0][0]:.2f}); "
                "this is recorded as an evidence gap rather than a conclusion until stronger evidence is available.",
                f"仅找到与{focus['zh']}有限相关的证据（{'、'.join(refs)}，相关度 {hits[0][0]:.2f}）；"
                "在获得更充分证据前，此处记为证据缺口而非结论。",
            )
        else:
            claim = bi(
                f"No evidence relevant to {focus['en']} was found; this is recorded as an evidence gap and no conclusion is asserted.",
                f"未找到与{focus['zh']}相关的证据；记为证据缺口，不作结论。",
            )
        gaps = [bi(f"No confident source for {focus['en']}", f"缺少{focus['zh']}的可靠依据")]
        questions = [card.gap_question] if card.gap_question and not answers else []
        status = "NEEDS_INPUT" if questions else "GAP"
        confidence = round(min(0.6, 0.4 + (hits[0][0] if hits else 0.0)), 3)
    return {
        "agent_id": card.id, "status": status, "claim": claim, "evidence_refs": refs if status == "SUPPORTED" else [],
        "retrieved_refs": refs, "confidence": confidence, "gaps": gaps,
        "actions": list(card.actions) if status == "SUPPORTED" else [],
        "questions": questions, "context": context_notes, "method": "rules",
    }


FINDING_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "specialist_finding", "strict": True,
        "schema": {
            "type": "object", "additionalProperties": False,
            "required": ["status", "claim_en", "claim_zh", "evidence_refs", "confidence", "gaps", "actions", "question_en", "question_zh"],
            "properties": {
                "status": {"type": "string", "enum": list(STATUSES)},
                "claim_en": {"type": "string"}, "claim_zh": {"type": "string"},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
                "gaps": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["en", "zh"],
                                                     "properties": {"en": {"type": "string"}, "zh": {"type": "string"}}}},
                "actions": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                        "required": ["text_en", "text_zh", "owner_en", "owner_zh"],
                                                        "properties": {"text_en": {"type": "string"}, "text_zh": {"type": "string"},
                                                                       "owner_en": {"type": "string"}, "owner_zh": {"type": "string"}}}},
                "question_en": {"type": "string"}, "question_zh": {"type": "string"},
            },
        },
    },
}


def validate_finding(data: dict, card: AgentCard, results: list[ToolResult]) -> dict | None:
    """Turn model JSON into a finding, or None when it is unusable."""
    if not isinstance(data, dict) or data.get("status") not in STATUSES or not str(data.get("claim_en") or "").strip():
        return None
    hits = _knowledge(results)
    retrieved = {doc.source_ref: score for score, doc in hits}
    canonical = {_norm(ref): ref for ref in retrieved}
    cited = [canonical.get(_norm(ref), ref) for ref in (data.get("evidence_refs") or []) if isinstance(ref, str)]
    status = data["status"]
    downgraded = False
    if any(ref not in retrieved for ref in cited):
        cited, status, downgraded = [ref for ref in cited if ref in retrieved], "GAP", True
    if status == "SUPPORTED" and not any(retrieved[ref] >= CONFIDENT_RELEVANCE for ref in cited):
        status, downgraded = "GAP", True
    try:
        confidence = max(0.0, min(0.97, float(data.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.5
    question = _bi({"en": data.get("question_en"), "zh": data.get("question_zh")})
    questions = [question] if question["en"] else []
    # A supported finding may still need a case fact; it keeps its question.
    if questions and status == "GAP":
        status = "NEEDS_INPUT"
    actions = [
        {"text": _bi({"en": a.get("text_en"), "zh": a.get("text_zh")}), "owner_role": _bi({"en": a.get("owner_en"), "zh": a.get("owner_zh")})}
        for a in (data.get("actions") or [])[:3] if isinstance(a, dict) and a.get("text_en")
    ] if status == "SUPPORTED" else []
    claim = _bi({"en": data["claim_en"], "zh": data.get("claim_zh")})
    if downgraded:
        claim = bi(f"Evidence gap: {claim['en']}", f"证据缺口：{claim['zh']}")
    return {
        "agent_id": card.id, "status": status, "claim": claim,
        "evidence_refs": cited if status == "SUPPORTED" else [], "retrieved_refs": list(retrieved),
        "confidence": round(confidence if status == "SUPPORTED" else min(confidence, 0.6), 3),
        "gaps": [_bi(g) for g in (data.get("gaps") or [])[:3]], "actions": actions or ([] if status != "SUPPORTED" else list(card.actions)),
        "questions": questions, "context": [r.summary for r in results if r.tool != "knowledge.search" and r.ok],
        "method": "llm", "downgraded": downgraded,
    }


async def model_finding(card: AgentCard, results: list[ToolResult], case_text: str, answers: list[str],
                        follow_up: str, budget, route, sensitivity) -> dict | None:
    if not budget.take():
        return None
    tools_text = "\n".join(f"[{r.tool}] {json.dumps(r.output, ensure_ascii=False, default=str)[:1500]}" for r in results)
    system = (
        f"You are the {card.name['en']} on an overseas infrastructure project. Your discipline: {card.focus['en']}. "
        "Use ONLY the tool results below. Cite knowledge sources by their exact source_ref. Choose SUPPORTED when a "
        "retrieved source states the rule, procedure or requirement that governs this case, even if case facts are still "
        "missing: state what the rule requires, recommend the action it implies, and ask for the missing fact in the "
        "question field. Choose GAP when no retrieved source governs the case, or NEEDS_INPUT when only the project team "
        "can supply what is needed. Never invent amounts, dates, clauses or names, and never accept or reject liability, "
        "cost or time. Claim at most two sentences; English and Simplified Chinese. Actions must name an owner role. Your "
        "authority is advisory only."
    )
    user = (f"Case:\n{case_text[:3000]}\n\nTool results:\n{tools_text}"
            + (f"\n\nAnswers already provided by the project team:\n" + "\n".join(answers) if answers else "")
            + (f"\n\nCoordinator follow-up for you: {follow_up}" if follow_up else ""))
    try:
        raw = await generate(system, user, response_format=FINDING_FORMAT, route=route, sensitivity=sensitivity)
    except LLMError:
        return None
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return None
    try:
        return validate_finding(json.loads(match.group(0)), card, results)
    except ValueError:
        return None
