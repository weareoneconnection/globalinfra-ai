"""Field reports into the agent organization.

A synced field observation is classified with the same intake rules as the
assistant, its case gets the higher of the reporter's severity and the AI's
risk (never lower), and the agent organization analyses it in the
background so the field user is not kept waiting. ``report_payload`` gives
the reporter the outcome: status, risk review, plan and open questions.
"""
from __future__ import annotations

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .i18n import bi
from .intake import LANGUAGE_DISPLAY, build_intake_result
from .models import AgentTrace, Case, CaseInput, FieldObservation, IntakeSubmission

log = logging.getLogger(__name__)

RISK_ORDER = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

# The reporter's category is a hint for classification, not the case type.
EVENT_HINTS = {
    "inspection": "Site inspection finding.",
    "ncr": "Non-conformance (NCR) defect found.",
    "rfi": "Request for information on design or drawing.",
    "hse": "HSE safety observation.",
    "progress": "Progress and schedule delay observation.",
    "delivery": "Supplier delivery observation.",
    "commissioning": "Commissioning observation.",
    "maintenance": "Maintenance observation.",
}


def higher_risk(reported: str, assessed: str) -> str:
    ranks = {r: i for i, r in enumerate(RISK_ORDER)}
    return max((reported, assessed), key=lambda r: ranks.get(r, 0))


def classify_report(event_type: str, description: str, twin_id: str | None) -> tuple[str, dict]:
    text = " ".join(part for part in (EVENT_HINTS.get(event_type, ""), description, f"Twin {twin_id}." if twin_id else "") if part)
    return text, build_intake_result(text)


def prepare_case(db: Session, case: Case, observation: FieldObservation, text: str, result: dict) -> None:
    """Type, risk, deadline and issues from intake; keep the full text for the agents."""
    final = higher_risk(observation.severity, result["risk"])
    case.type = result["case_type_label"]
    case.risk = final
    case.deadline = result["deadline"] or bi("To be triaged", "待分诊")
    case.detected_issues = result["issues"]
    case.source_language = LANGUAGE_DISPLAY.get(result["language"], bi(result["language"]))
    observation.ai_risk = result["risk"]
    observation.analysis_status = "PENDING"
    db.add(IntakeSubmission(
        raw_input_ref=f"field:{observation.client_id}",
        input_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        parsed_text=text, detected_language=result["language"], case_id=case.id,
    ))


async def analyze_reports(observation_ids: list[str]) -> None:
    """Background task: run the agent organization for each new report."""
    from .workflow import analyze_case  # workflow imports the agent organization

    db = SessionLocal()
    try:
        for observation_id in observation_ids:
            observation = db.get(FieldObservation, observation_id)
            if observation is None or not observation.case_id:
                continue
            try:
                await analyze_case(db, observation.case_id)
                observation = db.get(FieldObservation, observation_id)
                observation.analysis_status = "ANALYZED"
            except Exception:  # a failed analysis must not lose the report
                log.exception("field analysis failed for %s", observation_id)
                db.rollback()
                observation = db.get(FieldObservation, observation_id)
                observation.analysis_status = "FAILED"
            db.commit()
    finally:
        db.close()


def report_payload(db: Session, observation: FieldObservation) -> dict:
    case = db.get(Case, observation.case_id) if observation.case_id else None
    latest = db.scalar(select(AgentTrace.run_id).where(AgentTrace.case_id == observation.case_id, AgentTrace.kind == "team")
                       .order_by(AgentTrace.id.desc())) if case else None
    plan = []
    if latest:
        planner = db.scalar(select(AgentTrace).where(AgentTrace.run_id == latest, AgentTrace.kind == "planner"))
        plan = (planner.output or {}).get("steps", []) if planner else []
    questions = [
        {"id": row.id, "question": row.question, "status": row.status, "answer": row.answer}
        for row in db.scalars(select(CaseInput).where(CaseInput.case_id == observation.case_id).order_by(CaseInput.id))
    ] if case else []
    return {
        "id": observation.id, "client_id": observation.client_id, "project_id": observation.project_id,
        "twin_id": observation.twin_id, "event_type": observation.event_type, "description": observation.description,
        "captured_at": observation.captured_at.isoformat(), "attachments": observation.attachments,
        "analysis_status": observation.analysis_status, "case_id": observation.case_id,
        "risk_review": {
            "reported": observation.severity, "ai": observation.ai_risk, "final": case.risk if case else observation.severity,
            "raised": bool(case and observation.ai_risk and case.risk != observation.severity),
        },
        "case": None if case is None else {
            "status": case.status, "type": case.type, "deadline": case.deadline, "issues": case.detected_issues,
        },
        "plan": plan, "questions": questions,
    }
