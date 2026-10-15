"""Runs one case through the agent organization.

assemble team -> round 1 (tools + findings) -> coordinate -> round 2 follow-ups
-> plan -> verify. Every step is recorded as an AgentTrace. Model calls are
capped per case; with no model configured every step runs on deterministic
rules, so offline and CI behaviour stays reproducible.
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass, field
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain import PROJECT_INTELLIGENCE
from ..i18n import bi
from ..llm import LLMError, _route_order
from ..models import AgentTrace, Case, CaseInput, IntakeSubmission, Project
from ..retrieval import tokenize
from .cards import CARDS
from .coordination import build_plan, consolidate, detect_issues, model_issues, raw_actions, verify
from .findings import deterministic_finding, model_finding
from .team import Member, model_additions, rule_team
from .tools import TOOLS, ToolContext, ToolResult

MAX_MODEL_CALLS = 9
# Local gateways serve one request at a time; queueing many calls there only
# pushes later ones past the request timeout. Cloud endpoints run in parallel.
LOCAL_CONCURRENCY = 2
CLOUD_CONCURRENCY = 5
QUESTION_SIMILARITY = 0.35
MAX_QUESTIONS = 3


class Budget:
    def __init__(self, enabled: bool, limit: int = MAX_MODEL_CALLS, concurrency: int = CLOUD_CONCURRENCY):
        self.enabled, self.remaining, self.used = enabled, limit, 0
        self.slots = asyncio.Semaphore(concurrency)

    def take(self) -> bool:
        if not self.enabled or self.remaining <= 0:
            return False
        self.remaining -= 1
        self.used += 1
        return True


@dataclass
class OrgResult:
    run_id: str
    team: list[Member]
    findings: dict[str, dict]
    results: dict[str, list[ToolResult]]
    issues: list[dict]
    unresolved: list[dict]
    plan: list[dict]
    verification: dict
    questions: list[dict]
    model_calls: int
    traces: list[AgentTrace] = field(default_factory=list)

    @property
    def team_ids(self) -> list[str]:
        return [m.agent_id for m in self.team]


def _concurrency(route: str | None, sensitivity: str) -> int:
    try:
        providers = _route_order(route, sensitivity)
    except LLMError:
        return LOCAL_CONCURRENCY
    return LOCAL_CONCURRENCY if providers and providers[0].name == "local" else CLOUD_CONCURRENCY


def merge_questions(questions: list[dict]) -> list[dict]:
    """Ask each distinct question once; similar questions from several agents are merged."""
    merged: list[dict] = []
    for item in questions:
        tokens = set(tokenize(item["question"]["en"]))
        for kept in merged:
            other = set(tokenize(kept["question"]["en"]))
            if tokens and other and len(tokens & other) / len(tokens | other) >= QUESTION_SIMILARITY:
                kept.setdefault("also_from", []).append(item["agent_id"])
                break
        else:
            merged.append(dict(item))
    return merged[:MAX_QUESTIONS]


def _question_key(agent_id: str, question: dict) -> str:
    return f"{agent_id}:{hashlib.sha1(question['en'].encode()).hexdigest()[:16]}"


def load_answers(db: Session, case_id: str) -> list[str]:
    rows = db.scalars(select(CaseInput).where(CaseInput.case_id == case_id, CaseInput.status == "ANSWERED").order_by(CaseInput.id))
    return [f"{row.question.get('en', '')} -> {row.answer}" for row in rows if row.answer]


def _run_tools(ctx: ToolContext, agent_id: str, extra_query: str = "") -> list[ToolResult]:
    card = CARDS[agent_id]
    results = []
    for tool in card.tools:
        fn = TOOLS.get(tool)
        if fn is None:
            continue
        results.append(fn(ctx, card, extra_query) if tool == "knowledge.search" else fn(ctx, card))
    return results


async def _specialist(ctx: ToolContext, agent_id: str, llm: Budget, route, sensitivity, follow_up: str = "",
                      extra_query: str = "", rules_fallback: bool = True) -> tuple[list[ToolResult], dict | None, int]:
    started = perf_counter()
    results = _run_tools(ctx, agent_id, extra_query)
    finding = None
    if llm.enabled:
        async with llm.slots:
            finding = await model_finding(CARDS[agent_id], results, ctx.full_text, ctx.answers, follow_up, llm, route, sensitivity)
    if finding is None and rules_fallback:
        finding = deterministic_finding(CARDS[agent_id], results, ctx.answers)
    return results, finding, max(1, round((perf_counter() - started) * 1000))


async def run_organization(db: Session, case: Case, project: Project | None, base_query: str, llm_enabled: bool,
                           route: str | None, sensitivity: str, core_map: dict, default_team: list[str]) -> OrgResult:
    run_id = uuid.uuid4().hex[:12].upper()
    country = project.country_code if project else None
    stage = (PROJECT_INTELLIGENCE.get(project.id, {}).get("phase") if project else None) or "construction"
    answers = load_answers(db, case.id)
    submission = db.scalar(select(IntakeSubmission).where(IntakeSubmission.case_id == case.id).order_by(IntakeSubmission.id.desc()))
    full_text = submission.parsed_text if submission and submission.parsed_text else base_query
    ctx = ToolContext(db=db, case=case, project=project, country=country, stage=stage,
                      base_query=" ".join([base_query, *answers]), answers=answers,
                      full_text=" ".join([full_text, *answers]))
    llm = Budget(llm_enabled, concurrency=_concurrency(route, sensitivity))
    traces: list[AgentTrace] = []
    case_type = (case.type or {}).get("en", "")

    # 1+2. team and round 1. The rule team starts working at once; the model's
    # proposed additions are computed in parallel and join as soon as known.
    started = perf_counter()
    team = rule_team(ctx.full_text, case_type, case.risk, core_map, default_team, label=case.type or {})
    core_tasks = [_specialist(ctx, m.agent_id, llm, route, sensitivity) for m in team]
    additions_task = model_additions(ctx.full_text, team, llm, route, sensitivity)
    gathered = await asyncio.gather(additions_task, *core_tasks)
    additions, outcomes = gathered[0], list(gathered[1:])
    if additions:
        outcomes += await asyncio.gather(*[_specialist(ctx, m.agent_id, llm, route, sensitivity) for m in additions])
        team += additions
    traces.append(AgentTrace(case_id=case.id, run_id=run_id, kind="team", agent_id="router", round=0,
                             output={"team": [m.payload() for m in team]}, method="llm" if additions else "rules",
                             duration_ms=max(1, round((perf_counter() - started) * 1000))))
    ids = [m.agent_id for m in team]
    results = {a: o[0] for a, o in zip(ids, outcomes)}
    findings = {a: o[1] for a, o in zip(ids, outcomes)}
    for member, (res, finding, ms) in zip(team, outcomes):
        traces.append(AgentTrace(case_id=case.id, run_id=run_id, kind="specialist", agent_id=member.agent_id, round=1,
                                 status=finding["status"], rationale=member.rationale,
                                 tool_calls=[r.record() for r in res], output=finding, method=finding["method"], duration_ms=ms))

    # 3. coordination and one round of targeted follow-ups
    started = perf_counter()
    issues = detect_issues(findings)
    # The model looks for contradictions between conclusions; with fewer than
    # two evidence-backed findings there is nothing to contradict.
    if sum(f["status"] == "SUPPORTED" for f in findings.values()) >= 2:
        issues += [i for i in await model_issues(findings, llm, route, sensitivity)
                   if not any(i["follow_up"] == j["follow_up"] for j in issues)]
    # A second retrieval pass without a model would only re-rank the same
    # corpus with more of the agent's own terms, which can promote unrelated
    # sources. Follow-ups therefore run only when a model can reason about
    # the coordinator's question; otherwise issues go straight to a human.
    # Gaps already become questions for people; only conflicts get a follow-up.
    follow_ups = {}
    if llm.enabled:
        for issue in issues:
            if issue["type"] == "conflict":
                follow_ups.setdefault(issue["follow_up"], issue)
    round2 = await asyncio.gather(*[
        _specialist(ctx, agent_id, llm, route, sensitivity, follow_up=issue["topic"]["en"], extra_query=issue.get("query", ""),
                    rules_fallback=False)  # only a model can resolve a follow-up; never re-rank with rules
        for agent_id, issue in follow_ups.items()
    ])
    resolved = []
    for (agent_id, issue), (res, finding, ms) in zip(follow_ups.items(), round2):
        if finding is None:  # model unavailable: the round-1 finding stands
            continue
        improved = finding["status"] == "SUPPORTED" and findings[agent_id]["status"] != "SUPPORTED"
        if improved:
            findings[agent_id], results[agent_id] = finding, res
            resolved.append(agent_id)
        traces.append(AgentTrace(case_id=case.id, run_id=run_id, kind="specialist", agent_id=agent_id, round=2,
                                 status=finding["status"], rationale=issue["topic"], tool_calls=[r.record() for r in res],
                                 output={**finding, "adopted": improved}, method=finding["method"], duration_ms=ms))
    unresolved = [i for i in issues if i["follow_up"] not in resolved and i["type"] == "conflict"]
    traces.append(AgentTrace(case_id=case.id, run_id=run_id, kind="coordinator", agent_id="coordinator", round=2,
                             status="ESCALATED" if unresolved else "COMPLETED",
                             output={"issues": issues, "resolved_by_follow_up": resolved, "unresolved": unresolved},
                             method="llm" if any(i.get("method") == "llm" for i in issues) else "rules",
                             duration_ms=max(1, round((perf_counter() - started) * 1000))))

    # 4. questions for humans (deduplicated, persisted across re-analysis)
    raw_questions = [
        {"agent_id": agent_id, "question": question, "key": _question_key(agent_id, question)}
        for agent_id in ids for question in findings[agent_id].get("questions", [])
    ]
    actions = raw_actions(ids, findings)
    merged_actions, merged_questions = await consolidate(actions, raw_questions, llm, route, sensitivity)
    questions = (merged_questions if merged_questions is not None else merge_questions(raw_questions))[:MAX_QUESTIONS]

    # 5. plan and verification
    plan = build_plan(ids, findings, questions, case.deadline, case.risk, unresolved, merged_actions)
    verification = verify(ids, findings, plan, unresolved)
    verification["model_calls"] = llm.used
    traces.append(AgentTrace(case_id=case.id, run_id=run_id, kind="planner", agent_id="planning", round=3, output={"steps": plan}))
    traces.append(AgentTrace(case_id=case.id, run_id=run_id, kind="verifier", agent_id="verification", round=3,
                             status="PASSED" if verification["passed"] else "FAILED", output=verification))
    return OrgResult(run_id, team, findings, results, issues, unresolved, plan, verification, questions, llm.used, traces)


def persist(db: Session, case_id: str, org: OrgResult) -> list[CaseInput]:
    # Earlier runs are kept for scorecards and audit; readers use the latest run_id.
    db.add_all(org.traces)
    existing = {row.question_key: row for row in db.scalars(select(CaseInput).where(CaseInput.case_id == case_id))}
    rows = []
    for item in org.questions:
        row = existing.get(item["key"])
        if row is None:
            row = CaseInput(case_id=case_id, agent_id=item["agent_id"], question_key=item["key"], question=item["question"], status="OPEN")
            db.add(row)
        rows.append(row)
    return rows


def team_summary(org: OrgResult) -> dict:
    names_en = ", ".join(CARDS[a].name["en"] for a in org.team_ids)
    names_zh = "、".join(CARDS[a].name["zh"] for a in org.team_ids)
    added = [m for m in org.team if m.source != "core"]
    return bi(
        f"Assembled a {len(org.team)}-member team ({names_en}); {len(added)} added beyond the core team for this case's signals.",
        f"组建 {len(org.team)} 人团队（{names_zh}）；其中 {len(added)} 人根据案例信号在核心团队之外加入。",
    )


def coordinator_summary(org: OrgResult) -> dict:
    conflicts = [i for i in org.issues if i["type"] == "conflict"]
    gaps = [i for i in org.issues if i["type"] == "gap"]
    return bi(
        f"Found {len(conflicts)} dependency conflict(s) and {len(gaps)} evidence gap(s); {len(org.unresolved)} left for a human decision, "
        f"{len(org.questions)} question(s) for the project team.",
        f"发现 {len(conflicts)} 个依赖冲突和 {len(gaps)} 个证据缺口；{len(org.unresolved)} 个交由人工决定，向项目团队提出 {len(org.questions)} 个问题。",
    )
