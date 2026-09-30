import time
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from .models import Case, Evidence, AgentRun, Approval, Verification, KnowledgeDocument

def _run(db: Session, case_id: str, agent: str, summary: str, ms: int):
    db.add(AgentRun(case_id=case_id, agent=agent, status="COMPLETED", summary=summary, duration_ms=ms))

def analyze_case(db: Session, case_id: str):
    case = db.get(Case, case_id)
    if not case:
        raise KeyError(case_id)
    # Idempotent demo workflow: replace prior runtime artifacts.
    db.execute(delete(Evidence).where(Evidence.case_id == case_id))
    db.execute(delete(AgentRun).where(AgentRun.case_id == case_id))
    db.execute(delete(Verification).where(Verification.case_id == case_id))
    db.execute(delete(Approval).where(Approval.case_id == case_id))

    _run(db, case_id, "Intake Agent", f"Normalized {len(case.detected_issues)} issues and preserved source-language context.", 182)
    docs = list(db.scalars(select(KnowledgeDocument)))
    refs = {d.source_ref: d for d in docs}

    selected = []
    if case_id == "CASE-2026-0182":
        selected = [refs.get("CTR-A / Clause C-14.2"), refs.get("RM-03 / Rev C"), refs.get("SI-028"), refs.get("ENG-NOTE-017")]
        _run(db, case_id, "Contract Agent", "Found responsibility and temporary-works evidence; external-road scope must not be assumed without the responsibility matrix.", 426)
        _run(db, case_id, "Engineering Agent", "Crack responsibility cannot be assigned from the notice alone; crack location, width, chronology and causation evidence are required.", 391)
        _run(db, case_id, "Standards & Compliance Agent", "No unsupported local-law conclusion generated; response remains limited to the approved synthetic project evidence set.", 284)
        _run(db, case_id, "Localization Agent", "Prepared terminology-locked bilingual response context while preserving defined contractual terms.", 203)
        _run(db, case_id, "Action Planning Agent", "Created a six-step response plan: confirm scope, coordinate earthwork boundary, inspect crack, compile evidence, draft response, obtain Project Manager approval.", 337)
    else:
        selected = docs[:2]
        _run(db, case_id, "Engineering Agent", "Completed initial discipline review and identified evidence gaps.", 321)
        _run(db, case_id, "Action Planning Agent", "Generated governed action plan and human review checkpoint.", 296)

    for idx, doc in enumerate([x for x in selected if x]):
        db.add(Evidence(case_id=case_id, title=doc.title, source_type=doc.category, source_ref=doc.source_ref, excerpt=doc.summary, confidence=max(0.88, 0.97 - idx*0.02), verified=True))

    db.add(Approval(case_id=case_id, title="Approve external response / governed action", approver_role="Project Manager", status="PENDING", risk=case.risk))
    db.add(Verification(case_id=case_id, status="WARN", citation_score=1.0, evidence_score=0.94 if case_id=="CASE-2026-0182" else 0.86, consistency_score=0.97, findings=["Evidence-backed candidate action generated","External action blocked pending human approval"] ))
    _run(db, case_id, "Verification Agent", "Verified cited evidence and blocked external execution until required human approval is recorded.", 244)
    case.status = "AWAITING_APPROVAL"
    db.commit()
    return {"case_id":case_id,"status":case.status,"message":"Analysis completed; external action is gated by approval."}
