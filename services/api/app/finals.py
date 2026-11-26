"""Read-only, privacy-safe finals Mission Control projection.

The public competition endpoint is not a second Case/Approval/Receipt state
authority. It projects the existing synthetic golden thread and separately
signed release evidence. It deliberately does not read tenant-scoped ROI
measurements or claim model/country/financial results without reviewed
competition evidence.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .competition import GOLDEN_CASE_ID, GOLDEN_INPUT, _golden_snapshot, submission_evidence
from .database import get_db
from .governed_execution import governed_closure_is_intact
from .i18n import bi, get_lang, localize
from .intake import build_intake_result
from .models import (
    Action,
    AgentRun,
    Approval,
    Case,
    CompetitionSession,
    CountryPack,
    Evidence,
    ExecutionReceipt,
    Project,
    VerificationReceipt,
    utc_now,
)

router = APIRouter(prefix="/competition", tags=["finals-mission-control"])

SCORING_STANDARD = "C4AI_2026_FINAL_AI_OUTBOUND_11_ITEMS"
# How many recent closed judge sessions to inspect for an intact signed chain.
_RECENT_SESSION_SCAN = 20

# Delivery stage per official criterion. These describe what the product has
# demonstrably built, never a score: VERIFIED = reproducible in the judge
# sandbox or signed CI; BUILT = implemented, awaiting real-project data;
# ROADMAP = planned; LIVE = assessed by the jury on site.
CRITERION_STAGES = {
    "industry-pain": "VERIFIED",
    "technology-fusion": "VERIFIED",
    "business-model": "BUILT",
    "technical-route": "VERIFIED",
    "data-support": "BUILT",
    "report-quality": "BUILT",
    "scenario-fit": "VERIFIED",
    "scalability": "VERIFIED",
    "economic-impact": "BUILT",
    "overseas-promotion": "ROADMAP",
    "live-presentation": "LIVE",
}

# What exists today, stated positively. Evidence limits stay in the single
# disclosure block (``limits``) instead of being repeated on every row.
CRITERION_EVIDENCE = {
    "industry-pain": bi(
        "Multilingual overseas owner notice turned into a located risk, cited country evidence and a five-party signed response chain; reproducible by any judge.",
        "跨语言海外业主函件 → 定位风险、引用属地依据 → 五主体签名闭环；评委可现场复现。",
    ),
    "technology-fusion": bi(
        "Dispatcher + specialist agent organization + grounded retrieval + vocabulary-constrained LLM layers + data-residency routing + signed governance in one chain.",
        "总调度 + 专业智能体组织 + 证据检索 + 词表约束的大模型层 + 数据驻留路由 + 签名治理，融合为一条链路。",
    ),
    "business-model": bi(
        "Positioned as a cross-border project collaboration backbone and an auditable project deliverable (signed digital thread handed to the owner).",
        "定位为跨国项目协同底座与可审计的项目交付物（可移交业主的签名数字主线）。",
    ),
    "technical-route": bi(
        "International adaptation by design: Country/Domain Packs, multilingual intake, restricted data kept on local models, signed fail-closed release gates.",
        "国际适应性设计：国家包/专业包、多语接入、敏感数据只走本地模型、签名失败关闭的发布门禁。",
    ),
    "data-support": bi(
        "Typed intake with lineage, versioned country source indexes and multilingual glossaries; real overseas project data enters through the authorized pilot.",
        "带血缘的类型化接入、版本化国家来源索引与多语术语表；真实海外项目数据经授权试点接入。",
    ),
    "report-quality": bi(
        "Finals design report is organized by the official 11 criteria and bound to the frozen release.",
        "决赛设计报告按官方 11 项组织，并绑定冻结发布版本。",
    ),
    "scenario-fit": bi(
        "Malaysian rail owner-notice workflow covering tool outbound, localization and capability export.",
        "马来西亚铁路业主函件场景，覆盖工具出海、属地融合与能力输出。",
    ),
    "scalability": bi(
        "Four Country Packs (MY, ID, SA, AE) and six Domain Packs share one core contract; MY→AE switches language, authorities and permit gates by configuration.",
        "四个国家包（MY/ID/SA/AE）与六个专业包共用一套核心契约；MY→AE 通过配置切换语言、主管机关与许可关卡。",
    ),
    "economic-impact": bi(
        "Paired human-vs-AI timing and ROI recomputation are implemented; figures are published only from the authorized pilot.",
        "人工与 AI 配对计时及 ROI 复算已实现；数字仅来自授权试点。",
    ),
    "overseas-promotion": bi(
        "Rollout path: one country pack per market, project-by-project replication on the same core and private deployment for data residency.",
        "推广路径：每个市场一套国家包，同一核心逐项目复制，私有化部署满足数据驻留。",
    ),
    "live-presentation": bi(
        "Judge sandbox, signed evidence and the five-minute finals script are ready for live assessment.",
        "评委沙箱、签名证据与五分钟决赛脚本已就绪，待现场评定。",
    ),
}


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


def _latest_closed_session(db: Session) -> tuple[CompetitionSession, Action] | None:
    """Most recent judge session whose signed document chain is still intact."""
    rows = db.scalars(
        select(CompetitionSession)
        .where(CompetitionSession.status == "CLOSED")
        .order_by(CompetitionSession.created_at.desc())
        .limit(_RECENT_SESSION_SCAN)
    )
    for row in rows:
        action = db.scalar(
            select(Action)
            .where(Action.case_id == row.case_id)
            .order_by(Action.created_at.desc())
        )
        if action is not None and governed_closure_is_intact(db, action):
            return row, action
    return None


def _session_snapshot(db: Session, row: CompetitionSession, action: Action) -> dict:
    """Project one closed judge session into the shape ``_mission_steps`` reads.

    Every field comes from records the sandbox actually wrote; nothing is
    synthesized for presentation.
    """
    case = db.get(Case, row.case_id)
    project = db.get(Project, case.project_id) if case else None
    pack = db.get(CountryPack, project.country_code) if project else None
    approvals = list(
        db.scalars(select(Approval).where(Approval.case_id == row.case_id).order_by(Approval.id))
    )
    evidence = list(
        db.scalars(
            select(Evidence)
            .where(Evidence.case_id == row.case_id)
            .order_by(Evidence.confidence.desc(), Evidence.id)
        )
    )
    runs = list(db.scalars(select(AgentRun).where(AgentRun.case_id == row.case_id).order_by(AgentRun.id)))
    execution = db.scalar(select(ExecutionReceipt).where(ExecutionReceipt.action_id == action.id))
    verification = db.scalar(select(VerificationReceipt).where(VerificationReceipt.action_id == action.id))
    actors = {
        *(item.decided_by for item in approvals if item.decided_by),
        *([execution.executor] if execution and execution.executor else []),
        *([verification.verified_by] if verification and verification.verified_by else []),
        *([action.closed_by] if action.closed_by else []),
    }
    return {
        "intake": build_intake_result(GOLDEN_INPUT),
        "evidence": [{"source_ref": item.source_ref, "title": item.title} for item in evidence],
        "agents": [{"name": item.agent, "status": item.status} for item in runs],
        "approvals": [{"status": item.status} for item in approvals],
        "action": {"id": action.id, "status": action.status},
        "receipts": {
            "execution": None if execution is None else {"id": execution.id},
            "verification": None if verification is None else {"id": verification.id},
        },
        "country_pack": None if pack is None else {"code": pack.code, "status": pack.status},
        "project": {"country_code": project.country_code if project else "MY"},
        "complete": True,
        "source": {
            "kind": "JUDGE_SANDBOX_RUN",
            "session_id": row.id,
            "started_at": row.created_at.isoformat(),
            "closed_at": action.closed_at.isoformat() if action.closed_at else None,
            "distinct_actors": len(actors),
            "closure_digest": action.closure_digest,
            "synthetic": True,
        },
    }


@router.get("/finals/overview")
def finals_overview(
    db: Session = Depends(get_db),
    lang: str = Depends(get_lang),
):
    golden = _golden_snapshot(db)
    closed = _latest_closed_session(db)
    mission_source = (
        _session_snapshot(db, *closed)
        if closed is not None
        else {
            **golden,
            "source": {
                "kind": "CANONICAL_GOLDEN_RECORD",
                "session_id": None,
                "started_at": None,
                "closed_at": None,
                "distinct_actors": 0,
                "closure_digest": None,
                "synthetic": True,
            },
        }
    )
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
            "steps": _mission_steps(mission_source),
            "source": mission_source["source"],
            "case_record_status": golden["case"]["status"],
            "document_workflow": "DRAFT_VERIFIED" if mission_source["complete"] else "NOT_VERIFIED",
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
                "stage": CRITERION_STAGES.get(row["id"], "BUILT"),
                "evidence": CRITERION_EVIDENCE.get(row["id"], row["evidence"]),
                "evidence_ids": row["evidence_ids"],
            }
            for row in release_evidence["scorecard"]
        ],
        "limits": [
            bi("The scenario, project and source records are synthetic competition fixtures.", "场景、项目及其来源记录均为参赛合成数据。"),
            bi("The signed release status is verified separately from case-level business outcomes.", "受信发布状态与具体业务成果是不同的验证对象。"),
            bi("Document-draft completion never closes a physical safety hazard.", "函件草稿完成不代表现场安全隐患关闭。"),
            bi("Real model, ROI and country-law claims require their own independent evidence.", "真实模型、经济效益与属地法规主张必须分别取得独立证据。"),
            bi("Fixed regression results prove reproducibility on synthetic cases, not real-project accuracy.", "固定回归结果证明合成用例上的可复现性，不代表真实项目准确率。"),
            bi("Country-Pack comparisons show configuration differences, not legal opinions or foreign production deployments.", "国家包对照展示配置差异，不构成法律意见或海外生产落地。"),
            bi("Criterion stages describe delivery status, never awarded or forecast marks.", "评分项阶段只描述交付状态，不代表评委得分或预测。"),
        ],
    }
    return localize(payload, lang)
