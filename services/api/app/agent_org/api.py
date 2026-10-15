"""HTTP surface of the agent organization."""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..i18n import get_lang, localize
from ..llm import LLMError
from ..models import AgentTrace, Approval, Case, CaseInput, ExecutionReceipt, utc_now
from ..security import Principal, require_roles
from .cards import CARDS, GOVERNANCE_AGENTS

router = APIRouter(tags=["agent-organization"])


@router.get("/agents/cards")
def agent_cards(lang: str = Depends(get_lang)):
    return localize([card.payload() for card in CARDS.values()], lang)


def _final_findings(traces: list[AgentTrace]) -> dict[str, AgentTrace]:
    best: dict[str, AgentTrace] = {}
    for trace in traces:
        if trace.kind != "specialist":
            continue
        if trace.round == 1 or (trace.output or {}).get("adopted"):
            best[trace.agent_id] = trace
    return best


@router.get("/cases/{case_id}/agent-run")
def case_agent_run(case_id: str, db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    if db.get(Case, case_id) is None:
        raise HTTPException(404, "Case not found")
    latest = db.scalar(select(AgentTrace.run_id).where(AgentTrace.case_id == case_id, AgentTrace.kind == "team").order_by(AgentTrace.id.desc()))
    traces = list(db.scalars(select(AgentTrace).where(AgentTrace.case_id == case_id, AgentTrace.run_id == latest).order_by(AgentTrace.id))) if latest else []
    by_kind = {t.kind: t for t in traces if t.kind != "specialist"}
    team = (by_kind.get("team").output or {}).get("team", []) if by_kind.get("team") else []
    final = _final_findings(traces)
    findings = []
    for member in team:
        trace = final.get(member["agent_id"])
        if trace is None:
            continue
        out = trace.output or {}
        findings.append({
            "agent_id": member["agent_id"], "name": member["name"], "round": trace.round, "status": out.get("status"),
            "claim": out.get("claim"), "evidence_refs": out.get("evidence_refs", []), "confidence": out.get("confidence"),
            "gaps": out.get("gaps", []), "actions": out.get("actions", []), "questions": out.get("questions", []),
            "context": out.get("context", []), "method": out.get("method"), "tool_calls": trace.tool_calls,
            "duration_ms": trace.duration_ms,
        })
    coordinator = by_kind.get("coordinator")
    inputs = list(db.scalars(select(CaseInput).where(CaseInput.case_id == case_id).order_by(CaseInput.id)))
    payload = {
        "case_id": case_id, "run_id": traces[0].run_id if traces else None, "team": team, "findings": findings,
        "issues": (coordinator.output or {}).get("issues", []) if coordinator else [],
        "unresolved": (coordinator.output or {}).get("unresolved", []) if coordinator else [],
        "plan": (by_kind["planner"].output or {}).get("steps", []) if "planner" in by_kind else [],
        "verification": by_kind["verifier"].output if "verifier" in by_kind else None,
        "questions": [{"id": row.id, "agent_id": row.agent_id, "agent": CARDS[row.agent_id].name if row.agent_id in CARDS else row.agent_id,
                       "question": row.question, "status": row.status, "answer": row.answer} for row in inputs],
    }
    return localize(payload, lang)


class InputAnswer(BaseModel):
    input_id: int = Field(gt=0)
    answer: str = Field(min_length=1, max_length=4000)


@router.post("/cases/{case_id}/inputs")
async def answer_case_input(
    case_id: str, payload: InputAnswer,
    principal: Principal = Depends(require_roles("engineer", "project_manager", "field_user")),
    db: Session = Depends(get_db), lang: str = Depends(get_lang),
):
    """Record a human answer to an agent question, then re-run the analysis with it."""
    row = db.get(CaseInput, payload.input_id)
    if row is None or row.case_id != case_id:
        raise HTTPException(404, "Question not found for this case")
    row.answer, row.status = payload.answer.strip(), "ANSWERED"
    row.answered_by, row.answered_at = principal.subject, utc_now()
    db.commit()
    if db.scalar(select(ExecutionReceipt).where(ExecutionReceipt.case_id == case_id)):
        return {"case_id": case_id, "reanalyzed": False, "reason": "analysis is frozen after execution"}
    from ..workflow import analyze_case  # imported here: workflow depends on this package
    try:
        result = await analyze_case(db, case_id)
    except LLMError as exc:
        raise HTTPException(502, str(exc))
    return localize({**result, "reanalyzed": True}, lang)


@router.get("/agents/scorecards")
def agent_scorecards(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    stats = defaultdict(lambda: {"runs": 0, "supported": 0, "gap": 0, "needs_input": 0, "llm": 0, "duration": 0, "cases": set()})
    latest_runs = {}
    for trace in db.scalars(select(AgentTrace).where(AgentTrace.kind == "team").order_by(AgentTrace.id)):
        latest_runs[trace.case_id] = trace.run_id  # one (the latest) run per case
    for trace in db.scalars(select(AgentTrace).where(AgentTrace.kind == "specialist", AgentTrace.round == 1,
                                                      AgentTrace.run_id.in_(list(latest_runs.values()) or [""]))):
        s = stats[trace.agent_id]
        s["runs"] += 1
        s["supported" if trace.status == "SUPPORTED" else "needs_input" if trace.status == "NEEDS_INPUT" else "gap"] += 1
        s["llm"] += trace.method == "llm"
        s["duration"] += trace.duration_ms
        s["cases"].add(trace.case_id)
    rejected = {row.case_id for row in db.scalars(select(Approval).where(Approval.status == "REJECTED"))}
    cards = []
    for agent_id, card in CARDS.items():
        if agent_id in GOVERNANCE_AGENTS:
            continue
        s = stats.get(agent_id)
        runs = s["runs"] if s else 0
        cards.append({
            "agent_id": agent_id, "name": card.name, "group": card.group, "runs": runs,
            "supported_rate": round(s["supported"] / runs, 3) if runs else None,
            "gap_rate": round(s["gap"] / runs, 3) if runs else None,
            "needs_input_rate": round(s["needs_input"] / runs, 3) if runs else None,
            "llm_share": round(s["llm"] / runs, 3) if runs else None,
            "avg_duration_ms": round(s["duration"] / runs) if runs else None,
            "rejected_cases": len(s["cases"] & rejected) if s else 0,
        })
    cards.sort(key=lambda c: -c["runs"])
    return localize(cards, lang)


@router.get("/agents/runs")
def agent_runs(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    teams = list(db.scalars(select(AgentTrace).where(AgentTrace.kind == "team").order_by(AgentTrace.id.desc()).limit(limit)))
    verifiers = {t.run_id: t for t in db.scalars(select(AgentTrace).where(AgentTrace.kind == "verifier", AgentTrace.run_id.in_([t.run_id for t in teams])))}
    rows = []
    for trace in teams:
        case = db.get(Case, trace.case_id)
        verifier = verifiers.get(trace.run_id)
        rows.append({
            "run_id": trace.run_id, "case_id": trace.case_id, "title": case.title if case else None,
            "team": (trace.output or {}).get("team", []), "created_at": trace.created_at.isoformat(),
            "passed": (verifier.output or {}).get("passed") if verifier else None,
            "consistency_score": (verifier.output or {}).get("consistency_score") if verifier else None,
            "model_calls": (verifier.output or {}).get("model_calls") if verifier else None,
        })
    return localize(rows, lang)
