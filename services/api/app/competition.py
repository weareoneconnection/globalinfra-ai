"""Phase 9.1 competition golden thread and reproducible evaluation evidence.

The competition surface is an orchestration layer over the product's existing
intake, knowledge, agent, digital-twin and governed-execution contracts.  It is
deliberately not a second, hard-coded demo implementation: the golden case is
analysed by ``workflow.analyze_case`` and the final artifact is executed and
verified by the same trusted-action functions used by the normal case UI.

The 30-case AI-outbound benchmark is stored as JSONL next to the API image and
is evaluated at request/CI time.  Every displayed metric is therefore derived
from executable cases rather than being authored presentation copy.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .governed_execution import GovernedExecutionError, close_action, execute_action, verify_action
from .i18n import bi, get_lang, localize
from .intake import build_intake_result
from .models import (
    Action,
    AgentRun,
    Approval,
    Artifact,
    Case,
    CountryPack,
    Evidence,
    ExecutionReceipt,
    KnowledgeDocument,
    Project,
    TwinObject,
    TwinScheduleLink,
    TwinSource,
    VerificationReceipt,
    utc_now,
)
from .retrieval import KnowledgeIndex
from .workflow import analyze_case

router = APIRouter(prefix="/competition", tags=["competition-evidence"])

GOLDEN_CASE_ID = "CASE-GOLDEN-MY-001"
DATASET_VERSION = "ai-outbound-2026.10.14-v1"
DATASET_PATH = Path(__file__).resolve().parent.parent / "evals" / "competition_outbound.jsonl"
REQUIRED_INTAKE_KEYS = {
    "primary_domain", "professional_domain", "case_type", "classification_method",
    "extraction_method", "lifecycle_stage", "risk", "country", "language",
    "issues", "entities", "recommended_agents", "required_approvals", "confidence",
}

GOLDEN_INPUT = (
    "Malaysia MY-RAIL-A owner notice: at Station S12, a worker was observed "
    "near an unprotected edge during working at height. Fall protection, "
    "permit-to-work and competent-person evidence are required immediately."
)


def load_competition_cases() -> list[dict]:
    return [json.loads(line) for line in DATASET_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def seed_competition(db: Session) -> None:
    """Install the stable golden case without resetting an existing demo run."""
    if db.get(Case, GOLDEN_CASE_ID) is not None or db.get(Project, 1) is None:
        return
    intake = build_intake_result(GOLDEN_INPUT)
    db.add(Case(
        id=GOLDEN_CASE_ID,
        project_id=1,
        title=bi(
            "Malaysia station S12 working-at-height owner notice",
            "马来西亚 S12 车站高处作业业主通知",
        ),
        description=bi(
            GOLDEN_INPUT,
            "马来西亚 MY-RAIL-A 业主通知：S12 车站一名工人在高处作业时靠近无防护临边，"
            "须立即核验坠落防护、作业许可证和胜任人员证据。",
        ),
        type=intake["case_type_label"],
        risk=intake["risk"],
        status="NEW",
        deadline=intake["deadline"] or bi("Immediate", "立即处理"),
        source_language=bi("English / Chinese", "英文 / 中文"),
        detected_issues=intake["issues"],
        project_routing_confidence=0.98,
        routing_status="ROUTED",
    ))
    db.commit()


def evaluate_competition_cases(db: Session, include_cases: bool = True) -> dict:
    """Execute the public 30-case deterministic benchmark against live code/data."""
    cases = load_competition_cases()
    index = KnowledgeIndex(list(db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.status == "CURRENT"))))
    started = perf_counter()
    results: list[dict] = []
    evidence_expected = evidence_found = complete_citations = 0
    abstention_expected = abstention_passed = 0

    for case in cases:
        row_started = perf_counter()
        prediction = build_intake_result(case["text"])
        hits = index.search(case.get("evidence_query", ""), top_k=3)
        hit_refs = [doc.source_ref for _, doc in hits]
        expected_refs = case.get("expected_evidence", [])
        requires_abstention = bool(case.get("requires_abstention"))
        if expected_refs:
            evidence_expected += len(expected_refs)
            evidence_found += sum(ref in hit_refs for ref in expected_refs)
            complete_citations += int(all(ref in hit_refs for ref in expected_refs))
        if requires_abstention:
            abstention_expected += 1
            # A non-overlapping query must not be promoted into a citation.
            abstained = not hits or hits[0][0] < 0.08
            abstention_passed += int(abstained)
        else:
            abstained = False

        checks = {
            "country": prediction["country"] == case["expected_country"],
            "lifecycle": prediction["lifecycle_stage"]["id"] == case["expected_lifecycle"],
            "case_type": prediction["case_type"] == case["expected_type"],
            "risk": prediction["risk"] == case["expected_risk"],
            "schema": REQUIRED_INTAKE_KEYS.issubset(prediction),
            "deterministic_fallback": prediction["classification_method"] == "rules" and prediction["extraction_method"] == "rules",
            "evidence": all(ref in hit_refs for ref in expected_refs) if expected_refs else abstained,
        }
        results.append({
            "id": case["id"], "category": case["category"], "language": case["language"],
            "checks": checks, "passed": all(checks.values()),
            "prediction": {
                "country": prediction["country"], "lifecycle": prediction["lifecycle_stage"]["id"],
                "case_type": prediction["case_type"], "risk": prediction["risk"],
                "agents": prediction["recommended_agents"], "confidence": prediction["confidence"],
            },
            "citations": [{"source_ref": doc.source_ref, "score": round(score, 4)} for score, doc in hits],
            "latency_ms": round((perf_counter() - row_started) * 1000, 3),
        })

    def rate(check: str) -> float:
        return round(sum(result["checks"][check] for result in results) / max(len(results), 1) * 100, 1)

    supported_count = sum(bool(case.get("expected_evidence")) for case in cases)
    elapsed_ms = (perf_counter() - started) * 1000
    passed_cases = sum(result["passed"] for result in results)
    metrics = {
        "case_pass_rate": round(passed_cases / max(len(cases), 1) * 100, 1),
        "country_accuracy": rate("country"),
        "lifecycle_accuracy": rate("lifecycle"),
        "risk_accuracy": rate("risk"),
        "case_type_accuracy": rate("case_type"),
        "top3_evidence_recall": round(evidence_found / max(evidence_expected, 1) * 100, 1),
        "citation_completeness": round(complete_citations / max(supported_count, 1) * 100, 1),
        "unsupported_query_abstention": round(abstention_passed / max(abstention_expected, 1) * 100, 1),
        "schema_validity": rate("schema"),
        "deterministic_fallback_success": rate("deterministic_fallback"),
        "average_latency_ms": round(elapsed_ms / max(len(cases), 1), 3),
    }
    thresholds = {
        "case_pass_rate": 100, "country_accuracy": 90, "lifecycle_accuracy": 90,
        "risk_accuracy": 90, "case_type_accuracy": 90,
        "top3_evidence_recall": 85, "citation_completeness": 85,
        "unsupported_query_abstention": 90, "schema_validity": 100,
        "deterministic_fallback_success": 100,
    }
    gates = {name: metrics[name] >= minimum for name, minimum in thresholds.items()}
    category_counts = Counter(case["category"] for case in cases)
    payload = {
        "suite": "AI_OUTBOUND_COMPETITION_EVIDENCE",
        "dataset_version": DATASET_VERSION,
        "dataset_path": "services/api/evals/competition_outbound.jsonl",
        "total_cases": len(cases),
        "passed_cases": passed_cases,
        "status": "PASSED" if all(gates.values()) else "FAILED",
        "metrics": metrics,
        "thresholds": thresholds,
        "gates": gates,
        "category_coverage": dict(category_counts),
        "method": "Deterministic intake + live TF-IDF knowledge retrieval against versioned seeded evidence",
        "data_boundary": "Synthetic competition cases; no customer or personal data",
        "generated_at": "live-request",
    }
    if include_cases:
        payload["cases"] = results
    return payload


def _golden_snapshot(db: Session) -> dict:
    case = db.get(Case, GOLDEN_CASE_ID)
    if case is None:
        raise HTTPException(404, "Golden competition case is not seeded")
    project = db.get(Project, case.project_id)
    pack = db.get(CountryPack, project.country_code) if project else None
    action = db.scalar(select(Action).where(Action.case_id == case.id).order_by(Action.created_at.desc()))
    approvals = list(db.scalars(select(Approval).where(Approval.case_id == case.id).order_by(Approval.id)))
    evidence = list(db.scalars(select(Evidence).where(Evidence.case_id == case.id).order_by(Evidence.confidence.desc())))
    runs = list(db.scalars(select(AgentRun).where(AgentRun.case_id == case.id).order_by(AgentRun.id)))
    execution = db.scalar(select(ExecutionReceipt).where(ExecutionReceipt.action_id == action.id)) if action else None
    verification = db.scalar(select(VerificationReceipt).where(VerificationReceipt.action_id == action.id)) if action else None
    artifact = db.scalar(select(Artifact).where(Artifact.action_id == action.id)) if action else None
    twin = db.scalar(select(TwinObject).where(TwinObject.project_id == case.project_id).order_by(TwinObject.health_score))
    control = db.scalar(select(TwinScheduleLink).where(TwinScheduleLink.twin_id == twin.id)) if twin else None
    sources = list(db.scalars(select(TwinSource).where(TwinSource.project_id == case.project_id).order_by(TwinSource.source_type)))
    intake = build_intake_result(GOLDEN_INPUT)
    closed = bool(action and action.status == "CLOSED" and verification and verification.status == "VERIFIED")

    steps = [
        {"id": "9.1.1", "title": bi("Bilingual event intake", "双语事件接入"), "proof": bi(f"{intake['language']} · {intake['case_type']} · {intake['risk']}", f"{intake['language']} · {intake['case_type_label']['zh']} · {intake['risk_label']['zh']}"), "status": "VERIFIED"},
        {"id": "9.1.2", "title": bi("Country and lifecycle routing", "国家与生命周期路由"), "proof": bi(f"{project.code if project else '—'} · {intake['lifecycle_stage']['id']} · 98%", f"{project.code if project else '—'} · {intake['lifecycle_stage']['name']['zh']} · 98%"), "status": "VERIFIED"},
        {"id": "9.1.3", "title": bi("Malaysia country pack", "马来西亚国家包"), "proof": bi(f"{pack.version if pack else '—'} · {len(pack.permit_catalog) if pack else 0} gates", f"{pack.version if pack else '—'} · {len(pack.permit_catalog) if pack else 0} 个关卡"), "status": "VERIFIED" if pack else "PENDING"},
        {"id": "9.1.4", "title": bi("Grounded knowledge evidence", "知识证据检索"), "proof": bi(f"{len(evidence)} cited sources", f"{len(evidence)} 条已引用来源"), "status": "VERIFIED" if evidence else "READY"},
        {"id": "9.1.5", "title": bi("Twin impact context", "数字孪生影响定位"), "proof": bi(f"{twin.id if twin else '—'} · {control.schedule_variance_days if control else 0}d · {round((control.forecast-control.budget), 2) if control else 0}M", f"{twin.id if twin else '—'} · {control.schedule_variance_days if control else 0}天 · {round((control.forecast-control.budget), 2) if control else 0}M"), "status": "VERIFIED" if twin else "PENDING"},
        {"id": "9.1.6", "title": bi("Multi-agent plan and human gate", "多智能体计划与人工关卡"), "proof": bi(f"{len(runs)} agent runs · {len(approvals)} approval(s)", f"{len(runs)} 次智能体运行 · {len(approvals)} 项审批"), "status": "VERIFIED" if approvals and all(item.status == "APPROVED" for item in approvals) else "READY"},
        {"id": "9.1.7", "title": bi("Trusted execution and independent verification", "可信执行与独立核验"), "proof": bi(verification.id if verification else "Awaiting explicit human approval", verification.id if verification else "等待明确人工审批"), "status": "VERIFIED" if closed else "READY"},
    ]
    return {
        "phase": "9.1",
        "positioning": bi(
            "GlobalInfra AI — trusted AI execution for overseas transport infrastructure",
            "GlobalInfra AI——面向海外交通基础设施的可信 AI 执行平台",
        ),
        "case": {
            "id": case.id, "status": case.status, "title": case.title, "description": case.description,
            "risk": case.risk, "deadline": case.deadline, "synthetic": True,
        },
        "project": None if not project else {"id": project.id, "code": project.code, "name": project.name, "country_code": project.country_code},
        "intake": intake,
        "country_pack": None if not pack else {"code": pack.code, "name": pack.name, "version": pack.version, "status": pack.status, "permit_count": len(pack.permit_catalog), "disclaimer": pack.disclaimer},
        "steps": steps,
        "evidence": [{"source_ref": item.source_ref, "title": item.title, "confidence": item.confidence, "verified": item.verified} for item in evidence],
        "agents": [{"name": item.agent, "status": item.status, "summary": item.summary, "duration_ms": item.duration_ms} for item in runs],
        "approvals": [{"id": item.id, "role": item.approver_role, "status": item.status, "decided_by": item.decided_by} for item in approvals],
        "action": None if not action else {"id": action.id, "type": action.action_type, "status": action.status, "evidence_refs": action.evidence_refs},
        "twin": None if not twin else {
            "twin_id": twin.id, "name": twin.name, "health_score": twin.health_score,
            "schedule_variance_days": control.schedule_variance_days if control else 0,
            "cost_variance_m": round(control.forecast - control.budget, 2) if control else 0,
            "interfaces": [{"type": source.source_type, "status": source.status, "uri": source.uri} for source in sources],
        },
        "receipts": {
            "execution": None if not execution else {"id": execution.id, "status": execution.status, "input_digest": execution.input_digest, "output_digest": execution.output_digest, "artifact_ref": execution.artifact_ref},
            "verification": None if not verification else {"id": verification.id, "status": verification.status, "checks": verification.checks, "artifact_digest": verification.artifact_digest},
            "artifact": None if not artifact else {"id": artifact.id, "type": artifact.artifact_type, "digest": artifact.digest},
        },
        "complete": closed,
        "governance": bi(
            "The generated output is a draft only and is never sent externally. Explicit human approval is required before execution.",
            "生成内容仅为草案，绝不自动对外发送；执行前必须获得明确人工审批。",
        ),
        "data_boundary": bi("Synthetic competition data — no customer data", "参赛合成数据——不含客户数据"),
    }


class GoldenRunRequest(BaseModel):
    human_approval_confirmed: bool = False
    approver: str = Field(default="Competition demo operator", min_length=2, max_length=120)


@router.get("/golden-thread")
def golden_thread(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    return localize(_golden_snapshot(db), lang)


@router.post("/golden-thread/run")
async def run_golden_thread(payload: GoldenRunRequest, db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    if not payload.human_approval_confirmed:
        raise HTTPException(409, detail={"code": "HUMAN_APPROVAL_REQUIRED", "message": "Explicit human approval is required."})
    started = perf_counter()
    case = db.get(Case, GOLDEN_CASE_ID)
    if case is None:
        raise HTTPException(404, "Golden competition case is not seeded")
    action = db.scalar(select(Action).where(Action.case_id == case.id).order_by(Action.created_at.desc()))

    try:
        if not action:
            # Competition mode is deliberately reproducible and network-free;
            # the normal intake/API routes remain available for live models.
            await analyze_case(db, case.id, model_route="mock", data_classification="public")
            action = db.scalar(select(Action).where(Action.case_id == case.id).order_by(Action.created_at.desc()))
        if action and action.status != "CLOSED":
            approvals = list(db.scalars(select(Approval).where(Approval.case_id == case.id)))
            for approval in approvals:
                if approval.status != "APPROVED":
                    approval.status = "APPROVED"
                    approval.decided_by = payload.approver
                    approval.decided_at = utc_now()
            if approvals and all(item.status == "APPROVED" for item in approvals):
                action.status = "APPROVED"
                action.approved_at = utc_now()
                case.status = "APPROVED"
                db.commit()
            if action.status == "APPROVED":
                execute_action(db, action.id, executor="competition.governed.document.generate")
            action = db.get(Action, action.id)
            if action.status in {"EXECUTED", "VERIFICATION_FAILED"}:
                verify_action(db, action.id, verifier="competition.independent.verifier")
            action = db.get(Action, action.id)
            if action.status == "VERIFIED":
                close_action(db, action.id)
    except GovernedExecutionError as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc

    result = _golden_snapshot(db)
    result["run"] = {
        "status": "COMPLETED" if result["complete"] else "INCOMPLETE",
        "elapsed_ms": round((perf_counter() - started) * 1000, 2),
        "human_approval_recorded": True,
        "external_delivery_performed": False,
    }
    return localize(result, lang)


@router.get("/evaluation")
def competition_evaluation(
    include_cases: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return evaluate_competition_cases(db, include_cases=include_cases)


@router.get("/submission-evidence")
def submission_evidence(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    evaluation = evaluate_competition_cases(db, include_cases=False)
    payload = {
        "track": bi("AI Outbound", "AI 出海赛道"),
        "phase": "9.1",
        "three_routes": [
            {"id": "tool-export", "label": bi("Tool export", "工具出海"), "proof": bi("Multilingual intake, country packs and contract/compliance evidence", "多语接入、国家包与合同/合规证据")},
            {"id": "local-integration", "label": bi("Local integration", "属地融合"), "proof": bi("Local HSE training, authority gates and human accountability", "属地 HSE 培训、主管机关关卡与人工责任")},
            {"id": "capability-export", "label": bi("Capability export", "能力输出"), "proof": bi("Operational digital twin with six interoperable interfaces", "具备六类互操作接口的运营数字孪生")},
        ],
        "scorecard": [
            {"criterion": bi("Innovation", "创新性"), "max_score": 30, "evidence": bi("Country-aware multi-agent trusted execution + operational twin", "国家感知多智能体可信执行 + 运营数字孪生")},
            {"criterion": bi("Practicality", "实用性"), "max_score": 30, "evidence": bi(f"{evaluation['total_cases']} executable cases and measured gates", f"{evaluation['total_cases']} 条可执行用例与实测关卡")},
            {"criterion": bi("Completeness", "方案完整性"), "max_score": 40, "evidence": bi("One-click golden thread, receipts, CI dataset and reproducible APIs", "一键黄金主线、回执、CI 数据集与可复现 API")},
        ],
        "evaluation": evaluation,
        "reproducibility": {
            "api": "/competition/evaluation?include_cases=true",
            "dataset": "services/api/evals/competition_outbound.jsonl",
            "runner": "python evals/run_competition_eval.py",
        },
    }
    return localize(payload, lang)
