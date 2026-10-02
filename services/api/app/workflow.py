from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from .models import Case, Evidence, AgentRun, Approval, Verification, KnowledgeDocument
from .i18n import bi
from .llm import translate

# Agent display names used only inside the demo workflow narrative (distinct
# from the specialist registry in agents.py).
AGENT_LABELS = {
    "intake": bi("Intake Agent", "接收处理智能体"),
    "contract": bi("Contract Agent", "合同智能体"),
    "engineering": bi("Engineering Agent", "工程智能体"),
    "standards": bi("Standards & Compliance Agent", "标准与合规智能体"),
    "localization": bi("Localization Agent", "本地化智能体"),
    "planning": bi("Action Planning Agent", "行动规划智能体"),
    "verification": bi("Verification Agent", "核验智能体"),
}

async def _run(db: Session, case_id: str, agent_key: str, summary_en: str, ms: int):
    summary_zh = await translate(summary_en, "zh")
    db.add(AgentRun(case_id=case_id, agent=AGENT_LABELS[agent_key], status="COMPLETED", summary=bi(summary_en, summary_zh), duration_ms=ms))

async def analyze_case(db: Session, case_id: str):
    case = db.get(Case, case_id)
    if not case:
        raise KeyError(case_id)
    # Idempotent demo workflow: replace prior runtime artifacts.
    db.execute(delete(Evidence).where(Evidence.case_id == case_id))
    db.execute(delete(AgentRun).where(AgentRun.case_id == case_id))
    db.execute(delete(Verification).where(Verification.case_id == case_id))
    db.execute(delete(Approval).where(Approval.case_id == case_id))

    await _run(db, case_id, "intake", f"Normalized {len(case.detected_issues)} issues and preserved source-language context.", 182)
    docs = list(db.scalars(select(KnowledgeDocument)))
    refs = {d.source_ref: d for d in docs}

    selected = []
    if case_id == "CASE-2026-0182":
        selected = [refs.get("CTR-A / Clause C-14.2"), refs.get("RM-03 / Rev C"), refs.get("SI-028"), refs.get("ENG-NOTE-017")]
        await _run(db, case_id, "contract", "Found responsibility and temporary-works evidence; external-road scope must not be assumed without the responsibility matrix.", 426)
        await _run(db, case_id, "engineering", "Crack responsibility cannot be assigned from the notice alone; crack location, width, chronology and causation evidence are required.", 391)
        await _run(db, case_id, "standards", "No unsupported local-law conclusion generated; response remains limited to the approved synthetic project evidence set.", 284)
        await _run(db, case_id, "localization", "Prepared terminology-locked bilingual response context while preserving defined contractual terms.", 203)
        await _run(db, case_id, "planning", "Created a six-step response plan: confirm scope, coordinate earthwork boundary, inspect crack, compile evidence, draft response, obtain Project Manager approval.", 337)
    else:
        selected = docs[:2]
        await _run(db, case_id, "engineering", "Completed initial discipline review and identified evidence gaps.", 321)
        await _run(db, case_id, "planning", "Generated governed action plan and human review checkpoint.", 296)

    for idx, doc in enumerate([x for x in selected if x]):
        db.add(Evidence(case_id=case_id, title=doc.title, source_type=doc.category, source_ref=doc.source_ref, excerpt=doc.summary, confidence=max(0.88, 0.97 - idx*0.02), verified=True))

    approval_title_zh = await translate("Approve external response / governed action", "zh")
    approver_role = bi("Project Manager", "项目经理")
    db.add(Approval(case_id=case_id, title=bi("Approve external response / governed action", approval_title_zh), approver_role=approver_role, status="PENDING", risk=case.risk))
    finding_1 = await translate("Evidence-backed candidate action generated", "zh")
    finding_2 = await translate("External action blocked pending human approval", "zh")
    db.add(Verification(case_id=case_id, status="WARN", citation_score=1.0, evidence_score=0.94 if case_id=="CASE-2026-0182" else 0.86, consistency_score=0.97,
                         findings=[bi("Evidence-backed candidate action generated", finding_1), bi("External action blocked pending human approval", finding_2)]))
    await _run(db, case_id, "verification", "Verified cited evidence and blocked external execution until required human approval is recorded.", 244)
    case.status = "AWAITING_APPROVAL"
    db.commit()
    message_zh = await translate("Analysis completed; external action is gated by approval.", "zh")
    return {"case_id": case_id, "status": case.status, "message": bi("Analysis completed; external action is gated by approval.", message_zh)}
