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
from .llm import generate, is_llm_configured, translate
from .models import Action, AgentRun, Approval, Case, Claim, Evidence, ExecutionReceipt, KnowledgeDocument, Verification
from .retrieval import KnowledgeIndex, case_query_text

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

# Short bilingual domain-focus search terms per agent: bias the shared
# retrieval index toward that agent's discipline so two agents looking at
# the same case don't just echo the same single top hit. This is
# retrieval/synthesis plumbing, not the public agent directory the
# `/agents` endpoint shows to users, so it is kept here rather than in
# agents.py.
FOCUS_TERMS: dict[str, str] = {
    "contract": "contract clause responsibility matrix scope exclusion temporary works 合同 条款 责任 矩阵 范围 除外 临时工程",
    "engineering": "engineering technical evidence crack location width chronology causation structural 工程 技术 证据 裂缝 位置 宽度 时序 成因",
    "interface": "interface civil mep rail systems external boundary coordination earthwork 接口 土建 机电 轨道 系统 边界 协调 土方",
    "hse": "safety environment hazard control fall protection working at height ppe 安全 环境 危险源 管控 坠落 防护 高处作业",
    "compliance": "compliance permit local law regulation method statement approval 合规 许可 当地法规 施工方案 审批",
    "workforce": "workforce competency training productivity localization 人力 能力 资质 培训 生产率 本地化",
    "quality": "quality inspection ncr defect corrective action trend 质量 检验 不符合项 缺陷 纠正措施 趋势",
    "construction": "construction work package method site condition progress 施工 工作包 方法 现场条件 进度",
    "knowledge": "knowledge approved project memory standards lessons learned 知识 项目记忆 标准 经验教训",
}

FOCUS_LABEL: dict[str, dict] = {
    "contract": bi("contractual responsibility", "合同责任划分"),
    "engineering": bi("technical/engineering causation", "工程技术成因"),
    "interface": bi("cross-discipline interface coordination", "跨专业接口协调"),
    "hse": bi("safety and environmental control", "安全与环境管控"),
    "compliance": bi("local compliance and permitting", "当地合规与许可"),
    "workforce": bi("workforce competency and training", "人力资质与培训"),
    "quality": bi("inspection and defect disposition", "检验与缺陷处置"),
    "construction": bi("site execution and work packages", "现场施工与工作包"),
    "knowledge": bi("approved project precedent", "已批准的项目先例"),
}

# Similarity thresholds (see retrieval.KnowledgeIndex.search's cosine
# scores) calibrated against the seeded demo knowledge base: below
# MIN_RELEVANCE nothing is cited at all; between the two an agent cites
# what it found but flags it as a gap rather than a conclusion; at or
# above CONFIDENT_RELEVANCE the finding is treated as evidence-backed.
MIN_RELEVANCE = 0.05
CONFIDENT_RELEVANCE = 0.22
TOP_K_EVIDENCE = 2

APPROVER_ROLE = bi("Project Manager", "项目经理")


def _lang(value: dict, lang: str) -> str:
    return value.get(lang) or value.get("en") or next(iter(value.values()), "")


def _llm_ready(model_route: str | None = None, data_classification: str = "internal") -> bool:
    return is_llm_configured(model_route, data_classification)


async def _specialist_summary(
    agent_id: str,
    hits: list[tuple[float, object]],
    llm_ready: bool,
    model_route: str | None = None,
    data_classification: str = "internal",
) -> dict:
    """Build the (en, zh) finding text for one specialist agent."""
    focus = FOCUS_LABEL[agent_id]
    if llm_ready:
        evidence_lines = "\n".join(
            f"- [{doc.source_ref}] {doc.summary.get('en', '')} (similarity {score:.2f})" for score, doc in hits
        ) or "(nothing relevant found)"
        system = (
            "You are a specialist assurance agent on an overseas infrastructure project. "
            "Respond in at most two sentences. Only state what the evidence below actually supports; "
            "if it is insufficient to support a conclusion, say so explicitly instead of guessing."
        )
        user = f"Your discipline focus: {focus['en']}.\nRetrieved evidence:\n{evidence_lines}\nWrite your finding."
        routing = {}
        if model_route is not None:
            routing["route"] = model_route
        if data_classification != "internal":
            routing["sensitivity"] = data_classification
        english = (await generate(system, user, **routing)).strip()
        chinese = (await translate(english, "zh", **routing)).strip()
        return bi(english, chinese)

    if not hits:
        return bi(
            f"No evidence relevant to {focus['en']} was found in the knowledge base; no conclusion is asserted pending further input.",
            f"知识库中未找到与{focus['zh']}相关的证据；在获得进一步信息前不作结论。",
        )
    top_score, top_doc = hits[0]
    refs = ", ".join(doc.source_ref for _, doc in hits)
    if top_score < CONFIDENT_RELEVANCE:
        return bi(
            f"Only limited evidence for {focus['en']} was found ({refs}, similarity {top_score:.2f}); "
            "this is recorded as a gap rather than a conclusion until stronger evidence is available.",
            f"仅找到与{focus['zh']}有限相关的证据（{refs}，相关度 {top_score:.2f}）；"
            "在获得更充分证据前，此处记为证据缺口而非结论。",
        )
    return bi(
        f"Reviewed {len(hits)} evidence item(s) for {focus['en']}; top reference {top_doc.source_ref} — "
        f"\"{top_doc.summary.get('en', '')}\" (similarity {top_score:.2f}).",
        f"针对{focus['zh']}核查了 {len(hits)} 条证据；首要引用 {top_doc.source_ref} ——"
        f"“{top_doc.summary.get('zh', '')}”（相关度 {top_score:.2f}）。",
    )


def _plan_steps(specialist_ids: list[str], confident_ids: set[str]) -> tuple[list[str], list[str]]:
    steps_en = ["confirm scope and stakeholders"]
    steps_zh = ["确认范围与相关方"]
    for agent_id in specialist_ids:
        label = FOCUS_LABEL[agent_id]
        if agent_id in confident_ids:
            steps_en.append(f"act on the {label['en']} finding")
            steps_zh.append(f"依据{label['zh']}方面的结论采取行动")
        else:
            steps_en.append(f"close the {label['en']} evidence gap")
            steps_zh.append(f"补齐{label['zh']}方面的证据缺口")
    steps_en += ["compile the consolidated evidence package", "draft the governed response",
                 f"obtain {_lang(APPROVER_ROLE, 'en')} approval"]
    steps_zh += ["汇总完整证据包", "起草受管控的回复", f"获取{_lang(APPROVER_ROLE, 'zh')}审批"]
    return steps_en, steps_zh


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

    # --- specialists: real retrieval-grounded findings, selected by case type ---
    index = KnowledgeIndex(list(db.scalars(select(KnowledgeDocument))))
    base_query = case_query_text(case)
    specialist_ids = SPECIALISTS_BY_CASE_TYPE.get(case_type_en, DEFAULT_SPECIALISTS)

    evidence_by_ref: dict[str, dict] = {}
    cited_ids: list[str] = []
    confident_ids: set[str] = set()

    # Specialist findings are independent once retrieval has completed. Run
    # their model calls concurrently so a three-discipline case pays for one
    # model round-trip chain instead of three sequential chains.
    specialist_inputs = [
        (
            agent_id,
            [(score, doc) for score, doc in index.search(
                f"{base_query} {FOCUS_TERMS.get(agent_id, '')}", top_k=TOP_K_EVIDENCE
            ) if score >= MIN_RELEVANCE],
        )
        for agent_id in specialist_ids
    ]
    started_at = {agent_id: perf_counter() for agent_id, _ in specialist_inputs}
    summaries = await asyncio.gather(*[
        _specialist_summary(agent_id, hits, llm_ready, model_route, data_classification)
        for agent_id, hits in specialist_inputs
    ])

    for (agent_id, hits), summary in zip(specialist_inputs, summaries, strict=True):
        db.add(AgentRun(
            case_id=case_id, agent=AGENTS_BY_ID[agent_id]["name"], status="COMPLETED", summary=summary,
            duration_ms=max(1, round((perf_counter() - started_at[agent_id]) * 1000)),
        ))
        if hits:
            cited_ids.append(agent_id)
            if hits[0][0] >= CONFIDENT_RELEVANCE:
                confident_ids.add(agent_id)
            for score, doc in hits:
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

    # --- planning: an action plan derived from which specialists found what ---
    t0 = perf_counter()
    steps_en, steps_zh = _plan_steps(specialist_ids, confident_ids)
    db.add(AgentRun(
        case_id=case_id, agent=AGENTS_BY_ID["planning"]["name"], status="COMPLETED",
        summary=bi(
            f"Created a {len(steps_en)}-step response plan: " + "; ".join(steps_en) + ".",
            f"已生成 {len(steps_zh)} 步响应计划：" + "；".join(steps_zh) + "。",
        ),
        duration_ms=max(1, round((perf_counter() - t0) * 1000)),
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

    # --- verification: scores computed from this run's own evidence/findings ---
    t0 = perf_counter()
    total = len(specialist_ids)
    cited_count = len(cited_ids)
    confident_count = len(confident_ids)
    citation_score = round(cited_count / total, 3) if total else 0.0
    evidence_score = round(sum(i["confidence"] for i in evidence_by_ref.values()) / len(evidence_by_ref), 3) if evidence_by_ref else 0.0
    consistency_score = round(confident_count / total, 3) if total else 0.0
    confident_en = ", ".join(_lang(AGENTS_BY_ID[a]["name"], "en") for a in specialist_ids if a in confident_ids) or "none"
    confident_zh = "、".join(_lang(AGENTS_BY_ID[a]["name"], "zh") for a in specialist_ids if a in confident_ids) or "无"
    findings = [bi(
        f"{confident_count}/{total} specialist agent(s) reached a confident, evidence-backed finding ({confident_en}).",
        f"{confident_count}/{total} 个专业智能体给出了有证据支撑的确定性结论（{confident_zh}）。",
    )]
    if confident_count < total:
        findings.append(bi(
            f"{total - confident_count} specialist finding(s) were flagged as an evidence gap rather than a conclusion.",
            f"{total - confident_count} 项专业结论因证据不足被标记为缺口而非结论。",
        ))
    findings.append(bi("External action blocked pending human approval.", "对外行动已阻止，待人工审批。"))
    db.add(Verification(
        case_id=case_id, status="WARN", citation_score=citation_score, evidence_score=evidence_score,
        consistency_score=consistency_score, findings=findings,
    ))
    db.add(AgentRun(
        case_id=case_id, agent=AGENTS_BY_ID["verification"]["name"], status="COMPLETED",
        summary=bi(
            f"Verified {cited_count}/{total} specialist citation(s) against the knowledge base "
            f"(average evidence confidence {evidence_score:.2f}); blocked external execution pending required human approval.",
            f"对照知识库核验了 {cited_count}/{total} 项专业引用（平均证据置信度 {evidence_score:.2f}）；"
            "在获得所需人工审批前阻止对外执行。",
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
