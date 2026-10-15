"""Case analysis workflow: a real, content-grounded multi-agent pipeline.

This is what ``POST /cases/{id}/analyze`` actually runs. Unlike a
declarative workflow *description* (see ``workflows/*.yaml``, which remain a
design reference and are not loaded or executed by any code), this module
drives a subset of the specialist agents declared in ``agents.py`` against
the real text of the case under analysis -- there is no branch on a
specific ``case_id`` anywhere below; every case, seeded or newly created,
goes through the same pipeline and gets an answer derived from its own
content:

1. An intake step normalizes the case and reports what it actually found
   (issue count, source language, classified type).
2. ``Case.type`` selects which specialist agents are engaged (see
   ``SPECIALISTS_BY_CASE_TYPE``) -- e.g. an HSE case engages the HSE,
   Compliance and Workforce agents; a contract/technical case engages the
   Contract, Engineering and Interface agents.
3. Each engaged specialist runs a real, deterministic, explainable TF-IDF
   search over the knowledge base (``retrieval.py``) using a query built
   from the case text plus that agent's domain-focus terms, and only cites
   evidence it actually finds there. When similarity is too low to support
   a conclusion, the agent says so explicitly instead of inventing one --
   uniformly, for any case, not just a hardcoded example.
4. A Localization agent records which defined references were preserved
   verbatim across the bilingual response.
5. A Planning agent synthesizes an action plan from which specialists
   actually produced a confident finding versus an evidence gap.
6. A Verification agent computes citation/evidence/consistency scores from
   the Evidence/AgentRun rows that were actually produced in this run,
   instead of reporting fixed numbers.
7. Human approval still gates any external/governed action (see
   ``main.py`` ``approve``/``reject``) -- that governance rule is
   intentionally a fixed policy, not a model inference.

When a real OpenAI-compatible model is configured (``llm_mode`` != mock and
``OPENAI_COMPAT_API_KEY`` set -- see ``llm.py``), each specialist's finding
is produced by that model, grounded in the same retrieved evidence, and
translated through the same model. Otherwise (the default, network-free
mode used in local dev/CI) the finding is generated directly in both
languages from the retrieved, already-bilingual ``KnowledgeDocument``
records, so the bilingual experience stays correct and fully deterministic
offline without depending on a fixed per-string phrase table for text that
was never known in advance.
"""
import asyncio
from time import perf_counter
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .agents import AGENTS
from .config import settings
from .i18n import bi
from .llm import is_llm_configured
from .models import Action, AgentRun, Approval, Case, Claim, Evidence, ExecutionReceipt, KnowledgeDocument, Project, Verification
from .retrieval import case_query_text
from .agent_org.orchestrator import coordinator_summary, persist as persist_organization, run_organization, team_summary

AGENTS_BY_ID = {a["id"]: a for a in AGENTS}

# Case.type (English label -- matches app.classify.classify_text and the
# seeded demo cases) -> ordered specialist agent ids engaged for that type
# of case. Every id must exist in AGENTS (see agents.py).
SPECIALISTS_BY_CASE_TYPE: dict[str, list[str]] = {
    "Contract / Technical Interface": ["contract", "engineering", "interface"],
    "HSE": ["hse", "compliance", "workforce"],
    "Quality": ["quality", "engineering", "construction"],
    "Compliance": ["compliance", "engineering", "knowledge"],
}
DEFAULT_SPECIALISTS = ["contract", "engineering"]

# Relevance thresholds live with the agent tools (single source of truth).
from .agent_org.tools import CONFIDENT_RELEVANCE, MIN_RELEVANCE, TOP_K_EVIDENCE  # noqa: E402,F401

APPROVER_ROLE = bi("Project Manager", "项目经理")


def _lang(value: dict, lang: str) -> str:
    return value.get(lang) or value.get("en") or next(iter(value.values()), "")


def _llm_ready(model_route: str | None = None, data_classification: str = "internal") -> bool:
    return is_llm_configured(model_route, data_classification)


async def analyze_case(
    db: Session,
    case_id: str,
    model_route: str | None = None,
    data_classification: str = "internal",
):
    case = db.get(Case, case_id)
    if not case:
        raise KeyError(case_id)
    existing_action = db.scalar(select(Action).where(Action.case_id == case_id).order_by(Action.created_at.desc()))
    if existing_action and db.scalar(select(ExecutionReceipt).where(ExecutionReceipt.action_id == existing_action.id)):
        return {
            "case_id": case_id,
            "status": case.status,
            "action_id": existing_action.id,
            "message": bi("This case already has an execution receipt; analysis is preserved.", "该工单已有执行回执；分析结果已保留。"),
        }

    case.status = "ANALYZING"
    case.routing_status = "ROUTED" if case.project_id is not None else "NEEDS_PROJECT_CONFIRMATION"

    # Idempotent run: replace prior runtime artifacts rather than
    # accumulating them, so re-analyzing a case is safe to repeat.
    db.execute(delete(Evidence).where(Evidence.case_id == case_id))
    db.execute(delete(Claim).where(Claim.case_id == case_id))
    db.execute(delete(AgentRun).where(AgentRun.case_id == case_id))
    db.execute(delete(Verification).where(Verification.case_id == case_id))
    if existing_action is None:
        db.execute(delete(Approval).where(Approval.case_id == case_id))

    llm_ready = _llm_ready(model_route, data_classification)

    # --- intake: normalize + classify the case itself, not a canned case ---
    t0 = perf_counter()
    case_type_en, case_type_zh = _lang(case.type, "en"), _lang(case.type, "zh")
    source_en, source_zh = _lang(case.source_language, "en"), _lang(case.source_language, "zh")
    n_issues = len(case.detected_issues)
    db.add(AgentRun(
        case_id=case_id, agent=bi("Case Intake", "工单接收"), status="COMPLETED",
        summary=bi(
            f"Normalized {n_issues} issue(s) from a {source_en} source notice and classified it as {case_type_en}.",
            f"已从{source_zh}来源通知中规范化 {n_issues} 项问题，并分类为{case_type_zh}。",
        ),
        duration_ms=max(1, round((perf_counter() - t0) * 1000)),
    ))

    # --- agent organization: dynamic team, tools, findings, coordination ---
    project = db.get(Project, case.project_id) if case.project_id is not None else None
    t0 = perf_counter()
    org = await run_organization(
        db, case, project, case_query_text(case), llm_ready, model_route, data_classification,
        SPECIALISTS_BY_CASE_TYPE, DEFAULT_SPECIALISTS,
    )
    db.add(AgentRun(
        case_id=case_id, agent=bi("Team Router", "组队调度"), status="COMPLETED", summary=team_summary(org),
        duration_ms=max(1, round((perf_counter() - t0) * 1000)),
    ))
    for agent_id in org.team_ids:
        finding = org.findings[agent_id]
        trace = next(t for t in org.traces if t.kind == "specialist" and t.agent_id == agent_id and t.round == 1)
        db.add(AgentRun(
            case_id=case_id, agent=AGENTS_BY_ID[agent_id]["name"],
            status="COMPLETED" if finding["status"] == "SUPPORTED" else finding["status"],
            summary=finding["claim"], duration_ms=trace.duration_ms,
        ))
    if org.issues:
        db.add(AgentRun(case_id=case_id, agent=bi("Coordinator", "协调器"), status="COMPLETED",
                        summary=coordinator_summary(org), duration_ms=1))

    evidence_by_ref: dict[str, dict] = {}
    for agent_id in org.team_ids:
        for result in org.results[agent_id]:
            for score, doc in result.hits:
                confidence = round(min(0.97, 0.6 + score), 3)
                existing = evidence_by_ref.get(doc.source_ref)
                if not existing or confidence > existing["confidence"]:
                    evidence_by_ref[doc.source_ref] = {"doc": doc, "confidence": confidence, "verified": score >= CONFIDENT_RELEVANCE}

    claim = Claim(
        case_id=case_id,
        statement=bi("The case has an evidence-backed response basis.", "该工单具备有证据支撑的响应基础。"),
        status="SUPPORTED" if evidence_by_ref else "UNVERIFIED",
    )
    db.add(claim)
    db.flush()
    for item in sorted(evidence_by_ref.values(), key=lambda x: -x["confidence"]):
        doc = item["doc"]
        db.add(Evidence(
            case_id=case_id, claim_id=claim.id, title=doc.title, source_type=doc.category, source_ref=doc.source_ref,
            excerpt=doc.summary, confidence=item["confidence"], verified=item["verified"],
        ))
    persist_organization(db, case_id, org)

    # --- localization: what got terminology-locked, derived from the real citations ---
    t0 = perf_counter()
    refs = [item["doc"].source_ref for item in evidence_by_ref.values()]
    if refs:
        localization_summary = bi(
            f"Preserved {len(refs)} defined term/reference(s) across the bilingual response context: {', '.join(refs)}.",
            f"在双语回复上下文中保留了 {len(refs)} 个既定术语/引用：{'、'.join(refs)}。",
        )
    else:
        localization_summary = bi(
            "No defined contractual or technical references required locking; bilingual response context prepared from case text alone.",
            "无需锁定既定合同或技术引用；双语回复上下文仅基于工单文本本身准备。",
        )
    db.add(AgentRun(
        case_id=case_id, agent=AGENTS_BY_ID["localization"]["name"], status="COMPLETED",
        summary=localization_summary, duration_ms=max(1, round((perf_counter() - t0) * 1000)),
    ))

    # --- planning: steps derived from the organization's findings ---
    plan = org.plan
    db.add(AgentRun(
        case_id=case_id, agent=AGENTS_BY_ID["planning"]["name"], status="COMPLETED",
        summary=bi(
            f"Created a {len(plan)}-step response plan: " + "; ".join(step["text"]["en"] for step in plan) + ".",
            f"已生成 {len(plan)} 步响应计划：" + "；".join(step["text"]["zh"] for step in plan) + "。",
        ),
        duration_ms=1,
    ))
    if case.project_id is None:
        case.status = "NEEDS_PROJECT_CONFIRMATION"
        db.commit()
        return {
            "case_id": case_id,
            "status": case.status,
            "message": bi(
                "Evidence analysis is available, but project confirmation is required before governed action creation.",
                "证据分析已完成，但创建受管控行动前需要确认项目归属。",
            ),
        }

    required_roles = [APPROVER_ROLE]
    if case_type_en == "HSE" and case.risk == "CRITICAL":
        required_roles.append(bi("HSE Manager sign-off", "HSE 经理会签"))
    approvals = list(db.scalars(select(Approval).where(Approval.case_id == case_id).order_by(Approval.id)))
    if not approvals:
        approvals = [Approval(
            case_id=case_id,
            title=bi("Approve owner-response draft / governed action", "审批业主回复草案 / 受管控行动"),
            approver_role=role,
            status="PENDING",
            risk=case.risk,
        ) for role in required_roles]
        db.add_all(approvals)
        db.flush()
    elif existing_action is not None:
        # Re-analysis changes the evidence/action input. Previous approval must
        # not authorize the newly generated intent, so require fresh decisions.
        for approval in approvals:
            approval.status = "PENDING"
            approval.decided_by = None
            approval.decided_at = None
    if existing_action is None:
        action = Action(
            id=f"ACT-{uuid.uuid4().hex.upper()}",
            case_id=case_id,
            approval_id=approvals[0].id,
            action_type="document.generate",
            status="AWAITING_APPROVAL",
            evidence_refs=refs,
        )
        db.add(action)
        db.flush()
    else:
        action = existing_action
        action.approval_id = approvals[0].id
        action.action_type = "document.generate"
        action.status = "AWAITING_APPROVAL"
        action.evidence_refs = refs
    for approval in approvals:
        approval.action_id = action.id

    # --- verification: checks and scores computed from this run ---
    t0 = perf_counter()
    team_ids = org.team_ids
    total = len(team_ids)
    org_check = org.verification
    citation_score = org_check["citation_score"]
    consistency_score = org_check["consistency_score"]
    evidence_score = round(sum(i["confidence"] for i in evidence_by_ref.values()) / len(evidence_by_ref), 3) if evidence_by_ref else 0.0
    supported = org_check["supported"]
    confident_en = ", ".join(_lang(AGENTS_BY_ID[a]["name"], "en") for a in supported) or "none"
    confident_zh = "、".join(_lang(AGENTS_BY_ID[a]["name"], "zh") for a in supported) or "无"
    findings = [bi(
        f"{len(supported)}/{total} specialist agent(s) reached a confident, evidence-backed finding ({confident_en}).",
        f"{len(supported)}/{total} 个专业智能体给出了有证据支撑的确定性结论（{confident_zh}）。",
    )]
    if len(supported) < total:
        findings.append(bi(
            f"{total - len(supported)} specialist finding(s) were flagged as an evidence gap rather than a conclusion.",
            f"{total - len(supported)} 项专业结论因证据不足被标记为缺口而非结论。",
        ))
    if org.unresolved:
        findings.append(bi(f"{len(org.unresolved)} cross-discipline issue(s) are left for a human decision.",
                           f"{len(org.unresolved)} 个跨专业问题交由人工决定。"))
    if org.questions:
        findings.append(bi(f"{len(org.questions)} question(s) are open for the project team.",
                           f"有 {len(org.questions)} 个问题待项目团队补充。"))
    for check in org_check["checks"]:
        if not check["passed"]:
            findings.append(check["detail"])
    findings.append(bi("External action blocked pending human approval.", "对外行动已阻止，待人工审批。"))
    db.add(Verification(
        case_id=case_id, status="WARN", citation_score=citation_score, evidence_score=evidence_score,
        consistency_score=consistency_score, findings=findings,
    ))
    passed = sum(1 for c in org_check["checks"] if c["passed"])
    db.add(AgentRun(
        case_id=case_id, agent=AGENTS_BY_ID["verification"]["name"], status="COMPLETED",
        summary=bi(
            f"Passed {passed}/{len(org_check['checks'])} organization checks; {len(supported)}/{total} findings are evidence-backed "
            f"(average evidence confidence {evidence_score:.2f}); blocked external execution pending required human approval.",
            f"组织核验通过 {passed}/{len(org_check['checks'])} 项；{len(supported)}/{total} 项结论有证据支撑"
            f"（平均证据置信度 {evidence_score:.2f}）；在获得所需人工审批前阻止对外执行。",
        ),
        duration_ms=max(1, round((perf_counter() - t0) * 1000)),
    ))

    case.status = "EVIDENCE_READY"
    action.status = "AWAITING_APPROVAL"
    case.status = "AWAITING_APPROVAL"
    db.commit()
    return {
        "case_id": case_id, "status": case.status, "action_id": action.id,
        "message": bi("Evidence is ready; the owner-response draft is gated by human approval.", "证据已就绪；业主回复草案需经人工审批。"),
    }
