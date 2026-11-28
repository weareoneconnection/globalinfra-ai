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

import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .config import is_production_environment, settings
from .evaluation_artifacts import SUITE_SPECS, verified_release_summary
from .governed_execution import governed_closure_is_intact
from .i18n import bi, get_lang, localize
from .intake import build_intake_result
from .llm import routing_status
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
    TwinEvent,
    TwinObject,
    TwinScheduleLink,
    TwinSource,
    VerificationReceipt,
    utc_now,
)
from .retrieval import KnowledgeIndex
from .twin_sync import case_twin_ids

router = APIRouter(prefix="/competition", tags=["competition-evidence"])

GOLDEN_CASE_ID = "CASE-GOLDEN-MY-001"
# v2 (2026-11-26): three rows labelled id/ar whose text is English are relabelled en.
# Local-language notices are evaluated in evals/multilingual_intake.jsonl.
DATASET_VERSION = "ai-outbound-2026.11.26-v2"
DATASET_PATH = Path(__file__).resolve().parent.parent / "evals" / "competition_outbound.jsonl"
AGENT_ORG_DATASET_PATH = DATASET_PATH.parent / "agent_org.jsonl"
DISPATCH_DATASET_PATH = DATASET_PATH.parent / "assistant_dispatch.jsonl"
PRODUCT_VERSION = "V6.1"
API_ROOT = Path(__file__).resolve().parent.parent
CHECKOUT_ROOT = API_ROOT.parent.parent
REPO_ROOT = (
    CHECKOUT_ROOT
    if (CHECKOUT_ROOT / "services" / "api" / "evals").is_dir()
    else API_ROOT
)
CANONICAL_DATASET_PATHS = {
    spec["slug"]: spec["dataset"] for spec in SUITE_SPECS
}
RELEASE_EVIDENCE_PATH = (
    Path(settings.release_evidence_path)
    if settings.release_evidence_path
    else Path(__file__).resolve().parent.parent / "evidence" / "release-evidence.json"
)
REQUIRED_INTAKE_KEYS = {
    "primary_domain", "professional_domain", "case_type", "classification_method",
    "extraction_method", "lifecycle_stage", "risk", "country", "language",
    "issues", "entities", "recommended_agents", "required_approvals", "confidence",
}

GOLDEN_INPUT = (
    "Malaysia MY-RAIL-A owner notice: at Viaduct V-12 Pier P47, a worker was "
    "observed near an unprotected edge during work at height. Stop the work "
    "and submit fall protection, permit-to-work and competent-person evidence "
    "within 24 hours."
)


def load_competition_cases() -> list[dict]:
    return [json.loads(line) for line in DATASET_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def _dataset_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dataset_size(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _deployment_commit() -> str | None:
    """Resolve the immutable source revision the running deployment claims."""
    return (
        os.getenv("RAILWAY_GIT_COMMIT_SHA")
        or os.getenv("GIT_COMMIT_SHA")
        or settings.deployment_commit_sha
        or None
    )


def release_validation_checks(release_evidence: dict) -> dict[str, bool]:
    """Return the four release gates whose absence must fail closed."""
    validation = release_evidence.get("validation") or {}
    api_tests = validation.get("api_tests") or {}
    test_count = api_tests.get("tests")
    passed_count = api_tests.get("passed")
    failures = api_tests.get("failures")
    errors = api_tests.get("errors")
    skipped = api_tests.get("skipped")
    return {
        "api_tests": bool(
            api_tests.get("status") == "PASSED"
            and type(test_count) is int
            and test_count > 0
            and type(passed_count) is int
            and passed_count == test_count
            and type(failures) is int
            and failures == 0
            and type(errors) is int
            and errors == 0
            and type(skipped) is int
            and skipped == 0
        ),
        "web_build": validation.get("web_build") == "PASSED",
        "migration_check": validation.get("migration_check") == "PASSED",
        "full_stack_smoke": validation.get("full_stack_smoke") == "PASSED",
    }


def seed_competition(db: Session) -> None:
    """Install the stable golden case without resetting an existing demo run."""
    if db.get(Case, GOLDEN_CASE_ID) is not None or db.get(Project, 1) is None:
        return
    intake = build_intake_result(GOLDEN_INPUT)
    db.add(Case(
        id=GOLDEN_CASE_ID,
        organization_id="globalinfra-demo",
        project_id=1,
        title=bi(
            "Malaysia Pier P47 working-at-height owner notice",
            "马来西亚 P47 桥墩高处作业业主通知",
        ),
        description=bi(
            GOLDEN_INPUT,
            "马来西亚 MY-RAIL-A 业主通知：V-12 高架桥 P47 桥墩一名工人在高处作业时"
            "靠近无防护临边，须停止作业并在 24 小时内提交坠落防护、作业许可证和胜任人员证据。",
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
    expected_source_refs = sorted({
        ref for case in cases for ref in case.get("expected_evidence", [])
    })
    # The public benchmark must be hermetic: customer/project documents added
    # to the live database can neither improve the score nor leak through the
    # include_cases citation trace.
    index = KnowledgeIndex(list(db.scalars(select(KnowledgeDocument).where(
        KnowledgeDocument.status == "CURRENT",
        KnowledgeDocument.source_ref.in_(expected_source_refs),
        KnowledgeDocument.confidentiality == "PUBLIC",
    ))))
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
        "generated_at": utc_now().isoformat(),
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
    # Locate the element the work order names (e.g. Pier P47); fall back to the weakest asset.
    linked = case_twin_ids(db, case)
    twin = db.get(TwinObject, linked[0]) if linked else db.scalar(select(TwinObject).where(TwinObject.project_id == case.project_id).order_by(TwinObject.health_score))
    control = db.scalar(select(TwinScheduleLink).where(TwinScheduleLink.twin_id == twin.id)) if twin else None
    sources = list(db.scalars(select(TwinSource).where(TwinSource.project_id == case.project_id).order_by(TwinSource.source_type)))
    intake = build_intake_result(GOLDEN_INPUT)
    closed = governed_closure_is_intact(db, action)
    routing_confidence = round(float(intake.get("confidence") or 0) * 100)

    steps = [
        {"id": "9.1.1", "title": bi("Bilingual event intake", "双语事件接入"), "proof": bi(f"{intake['language']} · {intake['case_type']} · {intake['risk']}", f"{intake['language']} · {intake['case_type_label']['zh']} · {intake['risk_label']['zh']}"), "status": "DETERMINISTIC_REFERENCE"},
        {"id": "9.1.2", "title": bi("Country and lifecycle routing", "国家与生命周期路由"), "proof": bi(f"{project.code if project else '—'} · {intake['lifecycle_stage']['id']} · {routing_confidence}%", f"{project.code if project else '—'} · {intake['lifecycle_stage']['name']['zh']} · {routing_confidence}%"), "status": "DETERMINISTIC_REFERENCE"},
        {"id": "9.1.3", "title": bi("Malaysia country pack", "马来西亚国家包"), "proof": bi(f"{pack.version if pack else '—'} · {len(pack.permit_catalog) if pack else 0} gates", f"{pack.version if pack else '—'} · {len(pack.permit_catalog) if pack else 0} 个关卡"), "status": "REVIEWED" if pack and pack.status == "REVIEWED" and pack.review_due_at and pack.review_due_at > utc_now() else "LOCAL_REVIEW_REQUIRED" if pack else "PENDING"},
        {"id": "9.1.4", "title": bi("Grounded knowledge evidence", "知识证据检索"), "proof": bi(f"{len(evidence)} cited sources", f"{len(evidence)} 条已引用来源"), "status": "AVAILABLE" if evidence else "NOT_RUN"},
        {"id": "9.1.5", "title": bi("Twin impact context", "数字孪生影响定位"), "proof": bi(f"{twin.id if twin else '—'} · {control.schedule_variance_days if control else 0}d · {round((control.forecast-control.budget), 2) if control else 0}M", f"{twin.id if twin else '—'} · {control.schedule_variance_days if control else 0}天 · {round((control.forecast-control.budget), 2) if control else 0}M"), "status": "SYNTHETIC_AVAILABLE" if twin else "PENDING"},
        {"id": "9.1.6", "title": bi("Multi-agent plan and human gate", "多智能体计划与人工关卡"), "proof": bi(f"{len(runs)} agent runs · {len(approvals)} approval(s)", f"{len(runs)} 次智能体运行 · {len(approvals)} 项审批"), "status": "RECORDED" if approvals and all(item.status == "APPROVED" for item in approvals) else "AWAITING_ACTION"},
        {"id": "9.1.7", "title": bi("Trusted execution and independent verification", "可信执行与独立核验"), "proof": bi(verification.id if verification else "Awaiting explicit human approval", verification.id if verification else "等待明确人工审批"), "status": "VERIFIED" if closed else "AWAITING_ACTION"},
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
            "located_from_case": bool(linked),
            "work_order_events": [
                {"id": e.id, "status": e.status, "evidence_refs": e.evidence_refs}
                for e in db.scalars(select(TwinEvent).where(TwinEvent.twin_id == twin.id, TwinEvent.event_type == "WORK_ORDER").order_by(TwinEvent.occurred_at.desc()))
            ],
            "interfaces":[{"type": source.source_type, "status": source.status, "uri": source.uri} for source in sources],
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


@router.get("/golden-thread")
def golden_thread(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    return localize(_golden_snapshot(db), lang)


@router.post("/golden-thread/run", deprecated=True)
def retired_golden_thread_autorun():
    """The V5 one-click path is intentionally non-operational in V6.

    A boolean and a free-text name can never stand in for independent human
    identities. Judges must use the isolated, role-ticketed session endpoints.
    """
    raise HTTPException(
        410,
        detail={
            "code": "LEGACY_AUTORUN_REMOVED",
            "message": (
                "One-click approval/execution was removed in V6. Create a "
                "competition session and complete every governed step with "
                "a distinct role ticket."
            ),
            "next": "/competition/sessions",
        },
    )


@router.get("/evaluation")
def competition_evaluation(
    include_cases: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return evaluate_competition_cases(db, include_cases=include_cases)


def _release_evidence(deployment_commit: str | None, dataset_hashes: dict[str, str]) -> dict:
    """Load the CI artifact fail-closed; absence or tampering never becomes PASS."""
    if not RELEASE_EVIDENCE_PATH.is_file():
        return {
            "verification": {
                "status": "UNVERIFIED",
                "reasons": [
                    "RELEASE_EVIDENCE_MISSING",
                    *([] if deployment_commit else ["DEPLOYMENT_COMMIT_MISSING"]),
                ],
                "commit": None,
                "key_id": None,
            },
            "generated_at": None,
            "source": {"commit": None, "dirty": None},
            "ci": {"url": None},
            "model_configuration": routing_status(),
            "totals": {
                "expected_suite_count": 3,
                "complete_suite_count": 0,
                "case_count": sum(
                    _dataset_size(path)
                    for path in (
                        DATASET_PATH,
                        AGENT_ORG_DATASET_PATH,
                        DISPATCH_DATASET_PATH,
                    )
                ),
                "evidence_completeness": "INCOMPLETE",
            },
            "validation": {},
            "suites": [
                {
                    "id": suite_id,
                    "slug": slug,
                    "evidence_status": "UNVERIFIED",
                    "verification_errors": ["RUNNER_OUTPUT_MISSING"],
                    "reported_status": "NOT_RUN",
                    "case_count": _dataset_size(path),
                    "metrics": {},
                    "gates": {},
                    "dataset": {
                        "path": CANONICAL_DATASET_PATHS[slug],
                        "records": _dataset_size(path),
                        "sha256": dataset_hashes[slug],
                    },
                    "runner_output": {"filename": None, "sha256": None},
                }
                for suite_id, slug, path in (
                    ("AI_OUTBOUND_COMPETITION_EVIDENCE", "ai_outbound", DATASET_PATH),
                    ("AGENT_ORGANIZATION", "agent_organization", AGENT_ORG_DATASET_PATH),
                    ("ASSISTANT_DISPATCH", "assistant_dispatch", DISPATCH_DATASET_PATH),
                )
            ],
        }
    try:
        summary = verified_release_summary(
            RELEASE_EVIDENCE_PATH,
            expected_commit=deployment_commit,
            ed25519_public_key=(
                settings.evidence_verification_public_key or None
            ),
            hmac_key=(
                settings.evidence_signing_key or None
                if settings.evidence_allow_legacy_hmac
                or not is_production_environment(
                    settings.environment, settings.railway_environment
                )
                else None
            ),
            repo_root=REPO_ROOT,
        )
        if not deployment_commit:
            summary["verification"]["status"] = "UNVERIFIED"
            summary["verification"]["reasons"] = sorted({
                *(summary["verification"].get("reasons") or []),
                "DEPLOYMENT_COMMIT_MISSING",
            })
        return summary
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "verification": {
                "status": "UNVERIFIED",
                "reasons": [
                    "RELEASE_EVIDENCE_INVALID",
                    type(exc).__name__,
                    *([] if deployment_commit else ["DEPLOYMENT_COMMIT_MISSING"]),
                ],
            },
            "generated_at": None,
            "source": {},
            "ci": {},
            "model_configuration": routing_status(),
            "totals": {"case_count": 0, "evidence_completeness": "INCOMPLETE"},
            "validation": {},
            "suites": [],
        }


def current_release_evidence() -> dict:
    """Verify the installed artifact against this deployment and its datasets.

    This is the single runtime trust decision used by the competition surface
    and production-readiness endpoint.  Callers must never infer readiness
    merely from a configured key or an existing file.
    """
    datasets = {
        "ai_outbound": DATASET_PATH,
        "agent_organization": AGENT_ORG_DATASET_PATH,
        "assistant_dispatch": DISPATCH_DATASET_PATH,
    }
    return _release_evidence(
        _deployment_commit(),
        {name: _dataset_digest(path) for name, path in datasets.items()},
    )


@router.get("/submission-evidence")
def submission_evidence(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    evaluation = evaluate_competition_cases(db, include_cases=False)
    datasets = {
        "ai_outbound": DATASET_PATH,
        "agent_organization": AGENT_ORG_DATASET_PATH,
        "assistant_dispatch": DISPATCH_DATASET_PATH,
    }
    dataset_hashes = {name: _dataset_digest(path) for name, path in datasets.items()}
    model_routing = routing_status()
    deployment_commit = _deployment_commit()
    release_evidence = current_release_evidence()
    release_verified = release_evidence["verification"]["status"] == "VERIFIED"
    suite_presentation = {
        "AI_OUTBOUND_COMPETITION_EVIDENCE": (
            "ai-outbound",
            bi("AI outbound", "AI 出海"),
            "python evals/run_competition_eval.py",
            "/backend/competition/evaluation?include_cases=true",
        ),
        "AGENT_ORGANIZATION": (
            "agent-organization",
            bi("Agent organization 2.0", "智能体组织 2.0"),
            "python evals/run_agent_org_eval.py",
            "/agents",
        ),
        "ASSISTANT_DISPATCH": (
            "assistant-dispatch",
            bi("Dispatcher", "总调度智能体"),
            "python evals/run_dispatch_eval.py",
            "/",
        ),
    }
    evaluation_suites = []
    for suite in release_evidence.get("suites") or []:
        display = suite_presentation.get(
            suite.get("id"),
            (suite.get("slug", "unknown"), bi("Unknown suite", "未知评测"), "", "#"),
        )
        suite_gates = suite.get("gates") or {}
        suite_gates_valid = bool(suite_gates) and all(
            type(value) is bool for value in suite_gates.values()
        )
        suite_verified = (
            release_verified
            and suite.get("evidence_status") == "VERIFIED"
            and suite_gates_valid
        )
        reported_pass = (
            suite.get("reported_status") == "PASSED"
            and all(suite_gates.values())
        )
        total = int(suite.get("case_count") or 0)
        evaluation_suites.append(
            {
                "id": display[0],
                "label": display[1],
                "status": (
                    "VERIFIED_PASSED"
                    if suite_verified and reported_pass
                    else "VERIFIED_FAILED"
                    if suite_verified
                    else "UNVERIFIED"
                ),
                "passed_cases": total if suite_verified and reported_pass else 0,
                "total_cases": total,
                "dataset_version": suite.get("dataset", {}).get("sha256", "")[:16],
                "verification_mode": bi(
                    "Signed CI artifact bound to source commit",
                    "与源码提交绑定的签名 CI 证据包",
                ),
                "runner": display[2],
                "digest": suite.get("dataset", {}).get("sha256") or "",
                "metrics": suite.get("metrics") or {},
                "evidence_url": display[3],
                "verification_errors": suite.get("verification_errors") or [],
            }
        )
    total_cases = sum(item["total_cases"] for item in evaluation_suites)
    passed_cases = sum(item["passed_cases"] for item in evaluation_suites)
    validation = release_evidence.get("validation") or {}
    api_tests = validation.get("api_tests") or {}
    required_validation = release_validation_checks(release_evidence)
    validation_passed = all(required_validation.values())
    evidence_digest = release_evidence.get("artifact_sha256") or hashlib.sha256(
        json.dumps(dataset_hashes, sort_keys=True).encode("utf-8")
    ).hexdigest()
    ci_url = (release_evidence.get("ci") or {}).get("url")
    release_status = (
        "UNVERIFIED"
        if not release_verified
        else "VERIFIED_PASSED"
        if total_cases > 0 and passed_cases == total_cases and validation_passed
        else "VERIFIED_FAILED"
    )
    suite_status = {row["id"]: row["status"] for row in evaluation_suites}
    performance_evidence = bi(
        f"{passed_cases}/{total_cases} cases are backed by a commit-bound signed artifact; status {release_status}.",
        f"{passed_cases}/{total_cases} 条案例具有与提交绑定的签名证据；状态为 {release_status}。",
    )
    payload = {
        "track": bi("AI Outbound", "AI 出海赛道"),
        "phase": PRODUCT_VERSION,
        "release": {
            "product_version": PRODUCT_VERSION,
            "architecture": "governed-evidence-action",
            "generated_at": release_evidence.get("generated_at") or utc_now().isoformat(),
            "deployment_commit": deployment_commit[:12] if deployment_commit else "NOT_ATTESTED",
            "deployment_id": os.getenv("RAILWAY_DEPLOYMENT_ID", "runtime-not-exposed"),
            "evidence_status": release_status,
            "passed_cases": passed_cases,
            "total_cases": total_cases,
            "ci": {
                "provider": "GitHub Actions",
                "run_id": ci_url or "NOT_ATTESTED",
                "verified_at": release_evidence.get("generated_at"),
                "api_tests_passed": api_tests.get("passed"),
                "web_build": validation.get("web_build", "NOT_ATTESTED"),
                "migration_check": validation.get("migration_check", "NOT_ATTESTED"),
                "full_stack_smoke": validation.get("full_stack_smoke", "NOT_ATTESTED"),
            },
        },
        "three_routes": [
            {"id": "tool-export", "label": bi("Tool export", "工具出海"), "proof": bi("Multilingual intake, country packs and contract/compliance evidence", "多语接入、国家包与合同/合规证据")},
            {"id": "local-integration", "label": bi("Local integration", "属地融合"), "proof": bi("Local HSE training, authority gates and human accountability", "属地 HSE 培训、主管机关关卡与人工责任")},
            {"id": "capability-export", "label": bi("Capability export", "能力输出"), "proof": bi("Operational digital twin with six interoperable interfaces", "具备六类互操作接口的运营数字孪生")},
        ],
        "capabilities": [
            {"id": "ingestion", "label": bi("Six-channel ingestion", "六通道数据接入"), "proof": bi("Work orders, documents, master data, enterprise systems, BIM/GIS/twins and IoT keep domain semantics", "工单、文档、主数据、企业系统、BIM/GIS/孪生与 IoT 保留专业语义"), "href": "/data-ingestion", "status": "CODE_PRESENT"},
            {"id": "dispatcher", "label": bi("Dispatcher", "总调度智能体"), "proof": bi("Multi-intent decomposition, parallel specialist dispatch and citation-checked synthesis", "多意图拆解、专业智能体并行调度与引用核验汇总"), "href": "/", "status": suite_status.get("assistant-dispatch", "UNVERIFIED")},
            {"id": "organization", "label": bi("Agent organization 2.0", "智能体组织 2.0"), "proof": bi("Dynamic expert teams, governed tools, questions and traceable action plans", "动态专家组、受治理工具、补充提问与可追溯行动计划"), "href": "/agents", "status": suite_status.get("agent-organization", "UNVERIFIED")},
            {"id": "field", "label": bi("Field operations 2.0", "现场作业 2.0"), "proof": bi("Text, voice and validated media intake with risk-only-up AI assessment", "文字、语音、受校验媒体接入与风险只升不降的 AI 研判"), "href": "/field", "status": "CODE_PRESENT"},
            {"id": "twin", "label": bi("Operational digital twin", "运营数字孪生"), "proof": bi("IFC, glTF, 3D Tiles, GeoJSON, WMS and IoT-linked operational context", "IFC、glTF、3D Tiles、GeoJSON、WMS 与 IoT 运营上下文"), "href": "/twin", "status": "SYNTHETIC_DEMO_AVAILABLE"},
            {"id": "execution", "label": bi("Governed execution", "受控执行与独立核验"), "proof": bi("AI recommends; distinct humans approve, execute, verify, close and sign receipts", "AI 建议，不同人员审批、执行、核验、关闭并签署回执"), "href": "#golden-thread", "status": "POLICY_ENABLED" if settings.sod_enforced else "SANDBOX_ONLY"},
        ],
        "scoring_standard": "C4AI_2026_FINAL_AI_OUTBOUND_11_ITEMS",
        "scorecard": [
            {"id": "industry-pain", "category": bi("Innovation", "创新性"), "criterion": bi("Industry pain point resolution", "行业痛点解决能力"), "max_score": 10, "evidence": bi("Multilingual overseas owner notice and jurisdiction-aware evidence with an accountable workflow; synthetic demonstration, not a production result.", "海外业主函件多语理解、属地证据与责任流程；合成演示而非生产成效。"), "href": "#golden-thread", "evidence_ids": ["MY-RAIL-A","SYNTHETIC_DEMO"]},
            {"id": "technology-fusion", "category": bi("Innovation", "创新性"), "criterion": bi("Technology integration innovation", "技术融合创新性"), "max_score": 8, "evidence": bi("Dispatcher, specialist-team organization, grounded evidence and human authority; real-model comparative performance remains NOT_RUN.", "总调度、专业组队、证据约束与人工权责分离；真实模型对照仍为 NOT_RUN。"), "href": "/agents", "evidence_ids": ["AGENT_ORGANIZATION","MODEL_COMPARISON_NOT_RUN"]},
            {"id": "business-model", "category": bi("Innovation", "创新性"), "criterion": bi("Business model innovation", "业务模式突破性"), "max_score": 7, "evidence": bi("Configurable Country Pack capability delivery architecture; no claim of commercial deployment or adoption.", "国家包能力输出具备可配置架构；不宣称已商业部署或规模化应用。"), "href": "/country-packs", "evidence_ids": ["MY","ID","SA","AE","NO_PRODUCTION_ADOPTION_CLAIM"]},
            {"id": "technical-route", "category": bi("Technical Solution Design", "技术方案设计"), "criterion": bi("Technical route soundness", "技术路线合理性"), "max_score": 15, "evidence": bi("Constrained routing, human approval, signed execution receipts and fail-closed CI evidence; current deployment requires exact-commit verification.", "受约束路由、人工审批、签名执行回执与失败关闭CI证据；部署必须核验对应源码提交。"), "href": "/architecture", "evidence_ids": ["SIGNED_RELEASE_GATE","DEPLOYMENT_COMMIT_MATCH_REQUIRED"]},
            {"id": "data-support", "category": bi("Technical Solution Design", "技术方案设计"), "criterion": bi("Data support effectiveness", "数据支撑有效性"), "max_score": 10, "evidence": bi("Typed intake, provenance and official source indexes; seeded country packs still require qualified local review.", "类型化接入、血缘与官方来源索引；种子国家包仍须属地专业复核。"), "href": "/knowledge", "evidence_ids": ["SOURCE_INDEX_NOT_VERIFIED_FULL_TEXT","COUNTRY_PACK_EXPERT_REVIEW_REQUIRED"]},
            {"id": "report-quality", "category": bi("Solution Completeness", "方案完整性"), "criterion": bi("Design report quality", "设计报告规范性"), "max_score": 8, "evidence": bi("Finals report must map the official 11 criteria to the exact frozen release; historical V5.1 attachments are not current evidence.", "决赛报告须映射官方11项评分并绑定冻结版本；V5.1历史附件不作为最新证据。"), "href": "/competition", "evidence_ids": ["FINAL_REPORT_PENDING_VERSION_ALIGNMENT"]},
            {"id": "scenario-fit", "category": bi("Solution Completeness", "方案完整性"), "criterion": bi("Scenario applicability", "场景适配性"), "max_score": 7, "evidence": bi("Malaysian rail owner-notice workflow; draft verification does not verify physical hazard remediation.", "马来西亚铁路业主函件场景；草稿核验不等于现场隐患整改。"), "href": "#golden-thread", "evidence_ids": ["MY-RAIL-A","DOCUMENT_WORKFLOW_ONLY"]},
            {"id": "scalability", "category": bi("Solution Completeness", "方案完整性"), "criterion": bi("Scalability", "可扩展性"), "max_score": 5, "evidence": bi("Country and domain contracts are extendable; extra-country configurations are demos, not proven live rollouts.", "国家包与专业契约可扩展；其他国家配置属演示，不代表真实推广上线。"), "href": "/country-packs", "evidence_ids": ["MY","ID","SA","AE","DEMO_PACKS"]},
            {"id": "economic-impact", "category": bi("Application Value", "应用价值"), "criterion": bi("Quantified economic impact", "经济效益量化成果"), "max_score": 8, "evidence": bi("Pilot ROI recording exists, but no audited real-project savings are claimed from synthetic regressions.", "已有试点ROI记录，但不以合成回归宣称真实项目节时降本。"), "href": "/platform", "evidence_ids": ["NO_AUDITED_REAL_PROJECT_ROI_CLAIM"]},
            {"id": "overseas-promotion", "category": bi("Application Value", "应用价值"), "criterion": bi("Overseas rollout potential", "海外推广潜力"), "max_score": 7, "evidence": bi("Country/Domain Packs and region routing form a rollout architecture; no verified multi-country production adoption yet.", "国家/专业包及区域路由构成推广架构，尚无多国真实生产应用的验证。"), "href": "/country-packs", "evidence_ids": ["COUNTRY_PACK_ARCHITECTURE","NO_MULTICOUNTRY_PRODUCTION_CLAIM"]},
            {"id": "live-presentation", "category": bi("Live Presentation", "汇报效果"), "criterion": bi("On-site presentation", "现场汇报效果"), "max_score": 15, "evidence": bi("Reproducible judge sandbox and signed evidence are available; no score is inferred before live judging.", "可复现评委沙箱与签名证据已提供；现场汇报尚未评分。"), "href": "/competition/jury", "evidence_ids": ["JURY_SANDBOX","LIVE_PRESENTATION_NOT_SCORED"]},
        ],
        "evaluation": evaluation,
        "evaluation_suites": evaluation_suites,
        "governance": {
            "model_routing": model_routing,
            "data_boundary": bi("Synthetic competition data only; no customer or personal data is included", "仅使用参赛合成数据，不含客户数据或个人数据"),
            "authority_boundary": bi("AI may recommend and draft; named, separated humans retain approval, execution, verification and closure authority", "AI 可以建议与起草；审批、执行、核验和关闭权保留给相互分离的具名人员"),
            "external_delivery_performed": False,
            "lineage": {
                "source": "services/api/evals/*.jsonl",
                "transform": "versioned deterministic runners",
                "target": "competition submission evidence API",
            },
            "dataset_hashes": dataset_hashes,
            "evidence_digest": evidence_digest,
            "evidence_verification": release_evidence["verification"],
            "release_validation": {
                "status": (
                    "UNVERIFIED"
                    if not release_verified
                    else "PASSED"
                    if validation_passed
                    else "FAILED"
                ),
                "checks": required_validation,
            },
            "limitations": bi(
                "Results establish reproducibility on fixed synthetic suites; they are not production accuracy claims or a substitute for local professional review.",
                "结果仅证明固定合成评测集上的可复现性，不代表真实项目准确率，也不替代属地专业审查。",
            ),
        },
        "reproducibility": {
            "api": "/competition/evaluation?include_cases=true",
            "dataset": "services/api/evals/competition_outbound.jsonl",
            "runner": "python evals/run_competition_eval.py",
            "ci_run": ci_url or "NOT_ATTESTED",
        },
    }
    return localize(payload, lang)


@router.get("/evaluation-artifacts/latest")
def latest_evaluation_artifact():
    return current_release_evidence()


@router.get("/evidence-bundle")
def evidence_bundle():
    if not RELEASE_EVIDENCE_PATH.is_file():
        raise HTTPException(
            404,
            detail={
                "code": "RELEASE_EVIDENCE_MISSING",
                "message": "No CI release-evidence artifact is installed on this deployment.",
            },
        )
    release_evidence = current_release_evidence()
    verification = release_evidence.get("verification") or {}
    if verification.get("status") != "VERIFIED":
        raise HTTPException(
            409,
            detail={
                "code": "RELEASE_EVIDENCE_UNVERIFIED",
                "message": "The installed release-evidence artifact did not verify.",
                "reasons": verification.get("reasons") or [],
            },
        )
    try:
        raw = RELEASE_EVIDENCE_PATH.read_bytes()
        if hashlib.sha256(raw).hexdigest() != release_evidence.get("artifact_sha256"):
            raise HTTPException(
                409,
                detail={
                    "code": "RELEASE_EVIDENCE_CHANGED",
                    "message": "The release-evidence artifact changed after verification.",
                },
            )
        envelope = json.loads(raw)
    except HTTPException:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            422,
            detail={
                "code": "RELEASE_EVIDENCE_INVALID",
                "message": "The installed release-evidence artifact is invalid.",
            },
        ) from exc
    return {
        "artifact_sha256": release_evidence["artifact_sha256"],
        "envelope": envelope,
    }
