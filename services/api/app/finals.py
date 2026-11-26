"""Read-only, privacy-safe finals Mission Control projection.

The public competition endpoint is not a second Case/Approval/Receipt state
authority. It projects the existing synthetic golden thread and separately
signed release evidence. It deliberately does not read tenant-scoped ROI
measurements or claim model/country/financial results without reviewed
competition evidence.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .competition import GOLDEN_CASE_ID, _golden_snapshot, submission_evidence
from .database import get_db
from .i18n import bi, get_lang, localize
from .models import CountryPack, utc_now

router = APIRouter(prefix="/competition", tags=["finals-mission-control"])

SCORING_STANDARD = "C4AI_2026_FINAL_AI_OUTBOUND_11_ITEMS"


def _country_snapshot(db: Session, code: str) -> dict:
    pack = db.get(CountryPack, code)
    if pack is None:
        return {
            "code": code,
            "name": code,
            "status": "NOT_CONFIGURED",
            "release_gate": "CLOSED",
            "languages": [],
            "authorities": [],
            "permit_gates": [],
            "version": None,
        }
    fresh_human_review = bool(
        pack.status == "REVIEWED"
        and pack.reviewed_by
        and not pack.reviewed_by.startswith("seed:")
        and pack.review_due_at
        and pack.review_due_at > utc_now()
    )
    # A human review in the product records a gate, not an independent legal
    # certification. The finals view always discloses that limitation.
    return {
        "code": pack.code,
        "name": pack.name,
        "version": pack.version,
        "status": "REVIEW_RECORDED" if fresh_human_review else "EXPERT_REVIEW_REQUIRED",
        "release_gate": "REVIEW_RECORDED" if fresh_human_review else "CLOSED",
        "languages": pack.languages,
        "authorities": [item["code"] for item in pack.authorities],
        "permit_gates": [item["code"] for item in pack.permit_catalog],
        "source_digest": pack.source_digest,
        "source_type": "OFFICIAL_SOURCE_INDEX_NOT_VERIFIED_STATUTE",
    }


def _mission_steps(golden: dict) -> list[dict]:
    """Use real golden-state signals rather than synthetic success counters."""
    intake = golden["intake"]
    evidence = golden["evidence"]
    runs = golden["agents"]
    approvals = golden["approvals"]
    action = golden["action"]
    receipts = golden["receipts"]
    country_pack = golden["country_pack"]
    approved_count = sum(row["status"] == "APPROVED" for row in approvals)
    verified_draft = bool(golden["complete"] and receipts["verification"])
    steps = [
        {
            "id": "intake",
            "index": "01",
            "name": bi("Understand the notice", "理解海外业主函件"),
            "status": "DETERMINISTIC_REFERENCE",
            "detail": bi(
                f"{intake['case_type']} · {intake['risk']} · language {intake['language']}",
                f"{intake['case_type']} · {intake['risk']} · 语言 {intake['language']}",
            ),
            "evidence_ref": "competition.golden-thread.intake",
        },
        {
            "id": "localize",
            "index": "02",
            "name": bi("Localize sources and obligations", "属地规则与依据定位"),
            "status": (
                "EXPERT_REVIEW_REQUIRED"
                if not country_pack or country_pack["status"] != "REVIEWED"
                else "REVIEW_RECORDED"
            ),
            "detail": bi(
                f"Country {golden['project']['country_code']} · {len(evidence)} synthetic evidence records",
                f"国家 {golden['project']['country_code']} · {len(evidence)} 条合成证据记录",
            ),
            "evidence_ref": "competition.golden-thread.country_pack",
        },
        {
            "id": "coordinate",
            "index": "03",
            "name": bi("Coordinate specialist intelligence", "多专业智能体协同"),
            "status": "RECORDED" if runs else "NOT_RUN",
            "detail": bi(
                f"{len(runs)} stored specialist runs (synthetic scenario)",
                f"{len(runs)} 条已记录专业运行（合成场景）",
            ),
            "evidence_ref": "competition.golden-thread.agents",
        },
        {
            "id": "authorize",
            "index": "04",
            "name": bi("Keep humans accountable", "人工审批与责任分离"),
            "status": "APPROVED" if approvals and approved_count == len(approvals) else "AWAITING_APPROVAL",
            "detail": bi(
                f"{approved_count}/{len(approvals)} approvals recorded",
                f"已记录 {approved_count}/{len(approvals)} 项审批",
            ),
            "evidence_ref": "competition.golden-thread.approvals",
        },
        {
            "id": "execute",
            "index": "05",
            "name": bi("Generate a controlled draft", "受控生成函件草稿"),
            "status": "DRAFT_ONLY_NOT_SENT" if receipts["execution"] else "NOT_RUN",
            "detail": bi(
                f"Document action {action['status'] if action else 'NOT_RUN'}; external delivery never performed",
                f"函件行动状态 {action['status'] if action else 'NOT_RUN'}；没有对外发送",
            ),
            "evidence_ref": "competition.golden-thread.receipts.execution",
        },
        {
            "id": "verify",
            "index": "06",
            "name": bi("Verify document, not site remediation", "核验函件，不冒充现场整改"),
            "status": "DRAFT_VERIFIED" if verified_draft else "AWAITING_VERIFICATION",
            "detail": bi(
                "Physical hazard still awaits an on-site reinspection",
                "现场安全隐患仍需现场复检，不因函件草稿完成而关闭",
            ),
            "evidence_ref": "competition.golden-thread.receipts.verification",
        },
    ]
    return steps


@router.get("/finals/overview")
def finals_overview(
    db: Session = Depends(get_db),
    lang: str = Depends(get_lang),
):
    golden = _golden_snapshot(db)
    release_evidence = submission_evidence(db=db, lang=lang)
    release = release_evidence["release"]
    my = _country_snapshot(db, "MY")
    ae = _country_snapshot(db, "AE")
    payload = {
        "schema": "globalinfra.finals-mission.v1",
        "product_version": release["product_version"],
        "edition": "P2_FINALS_PRESENTATION",
        "track": bi("AI Outbound", "AI 出海赛道"),
        "scoring_standard": SCORING_STANDARD,
        "scenario": {
            "id": GOLDEN_CASE_ID,
            "title": golden["case"]["title"],
            "description": golden["case"]["description"],
            "project_code": golden["project"]["code"],
            "country_code": golden["project"]["country_code"],
            "risk": golden["case"]["risk"],
            "deadline": golden["case"]["deadline"],
            "data_boundary": "SYNTHETIC_COMPETITION_ONLY",
            "synthetic": True,
            "evidence": [
                {
                    "source_ref": row["source_ref"],
                    "title": row["title"],
                    "source_status": "SYNTHETIC_CASE_SOURCE",
                }
                for row in golden["evidence"][:5]
            ],
        },
        "mission": {
            "steps": _mission_steps(golden),
            "case_record_status": golden["case"]["status"],
            "document_workflow": "DRAFT_VERIFIED" if golden["complete"] else "NOT_VERIFIED",
            "physical_hazard": "REINSPECTION_NOT_PERFORMED",
            "project_safety_case_closed": False,
            "external_delivery_performed": False,
            "authority": "HUMAN_APPROVAL_REQUIRED",
            "runtime": "SYNTHETIC_GOLDEN_SNAPSHOT_NOT_LIVE_MODEL_BENCHMARK",
        },
        "release": {
            "status": release["evidence_status"],
            "commit": release["deployment_commit"],
            "version": release["product_version"],
            "verified_cases": release["passed_cases"],
            "total_cases": release["total_cases"],
            "ci_run": release["ci"]["run_id"],
            "verification_reason": release_evidence["governance"].get(
                "evidence_verification", {}
            ).get("reasons", []),
        },
        "business_impact": {
            "model_comparison": {
                "status": "NOT_RUN",
                "verified_score": None,
                "method": "evals/run_model_comparison.py",
                "boundary": bi(
                    "No independently reviewed four-arm real-model comparison is installed in the public finals evidence.",
                    "公开决赛证据中尚无经过独立复核的四组真实模型对照结果。",
                ),
            },
            "paired_roi": {
                "status": "NO_AUDITED_PUBLIC_RESULT",
                "baseline_minutes": None,
                "assisted_minutes": None,
                "improvement_percent": None,
                "boundary": bi(
                    "Tenant ROI records are never exposed publicly. No verified real-project saving is asserted.",
                    "租户ROI记录不会公开披露，当前不宣称已验证真实项目节约成果。",
                ),
            },
        },
        "country_adaptation": {
            "status": "CONFIGURATION_COMPARISON_ONLY",
            "first": my,
            "second": ae,
            "differences": {
                "languages": my["languages"] != ae["languages"],
                "authorities": my["authorities"] != ae["authorities"],
                "permit_gates": my["permit_gates"] != ae["permit_gates"],
            },
            "boundary": bi(
                "Country-Pack configuration comparison is not a legal opinion, verified statute corpus or second-country production deployment.",
                "国家包配置对比不等于法律意见、经核验的法规全文或第二国生产项目落地。",
            ),
        },
        "scorecard": [
            {
                "id": row["id"],
                "category": row["category"],
                "criterion": row["criterion"],
                "max_score": row["max_score"],
                "evidence": row["evidence"],
                "evidence_ids": row["evidence_ids"],
            }
            for row in release_evidence["scorecard"]
        ],
        "limits": [
            bi("The scenario, project and source records are synthetic competition fixtures.", "场景、项目及其来源记录均为参赛合成数据。"),
            bi("The signed release status is verified separately from case-level business outcomes.", "受信发布状态与具体业务成果是不同的验证对象。"),
            bi("Document-draft completion never closes a physical safety hazard.", "函件草稿完成不代表现场安全隐患关闭。"),
            bi("Real model, ROI and country-law claims require their own independent evidence.", "真实模型、经济效益与属地法规主张必须分别取得独立证据。"),
        ],
    }
    return localize(payload, lang)
