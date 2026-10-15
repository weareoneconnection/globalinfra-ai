"""Dispatching assistant: one message, several sub-agents.

``POST /assistant/dispatch`` is the assistant's orchestrator. Where
``/assistant/chat`` routes a message to exactly one tool, the dispatcher
plans up to ``MAX_STEPS`` steps, each served by a sub-agent from
``AGENTS``, runs them on the server and streams the progress to the client
as server-sent events:

``session`` -> ``plan`` -> ``step_start``/``step_done`` per step ->
``summary`` (or ``reply``) -> ``done``.

1. **Plan.** With a model, a schema-constrained plan names the sub-agent of
   every step and its arguments; case ids, project codes and question ids are
   checked against the database and the conversation's context. Without a
   model -- or when the plan does not validate -- a deterministic planner
   splits the message into clauses and routes each with the same keyword
   rules as ``/assistant/chat``, so a single-intent message is planned
   exactly as before.
2. **Run.** Independent steps run concurrently; a step that refers to the
   work order created earlier in the same plan (``case_id = "NEW"``) waits
   for it. Steps that write (intake, answering an agent question) never run
   at the same time. Every sub-agent acts through the platform's existing
   capabilities, so their governance is unchanged: approving, executing,
   verifying and closing are not sub-agents and stay human button actions.
3. **Summarise.** With two or more steps, a model writes a short summary that
   may only cite the steps (``[S1]``) and the sources they returned; anything
   else falls back to one deterministic line per step.
4. **Remember.** The conversation's recent turns and what "this case" and the
   current project refer to are kept server-side in ``AssistantSession``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .assistant import (
    _CASE_ID_RE, _CITATION_RE, _INCIDENT_RE, _JSON_RE, _KNOWLEDGE_RE, MAX_DIRECT_REPLY, ChatTurn,
    _grounded_answer, _hit_payload, _model_available, _project_in_text, _search, plan_rules,
)
from .database import SessionLocal, get_db
from .domain import PROJECT_INTELLIGENCE
from .i18n import bi, get_lang, localize
from .llm import LLMError, generate
from .models import (
    AgentTrace, Approval, AssistantSession, Case, CaseInput, ExecutionReceipt, FieldObservation, Project, utc_now,
)
from .security import Principal, get_principal, require_project

log = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["assistant"])

MAX_STEPS = 4
MAX_KNOWLEDGE_ANSWERS = 2       # model-written knowledge answers per message
STEP_TIMEOUT_S = 170
MAX_TURNS = 20
PLANNER_HISTORY = 8
MAX_SPLIT_LENGTH = 200          # longer messages (letters, notices) are never split
ANSWER_ROLES = {"engineer", "project_manager", "field_user"}

AgentId = Literal["intake", "knowledge", "case", "answer", "progress", "approvals", "field"]

AGENTS: dict[str, dict] = {
    "intake": {
        "name": bi("Intake agent", "建案智能体"), "authority": "creates_case",
        "role": bi("Turns a site issue or owner letter into a work order and convenes the agent organization.",
                   "把现场问题或业主函件转为工单，并召集智能体组织分析。"),
    },
    "knowledge": {
        "name": bi("Regulation agent", "法规智能体"), "authority": "read_only",
        "role": bi("Searches regulations and the knowledge base and answers only with citations.",
                   "检索法规与知识库，只依据引用作答。"),
    },
    "case": {
        "name": bi("Case follow-up agent", "案例跟进智能体"), "authority": "read_only",
        "role": bi("Reports a work order's status, plan, open questions and approvals.",
                   "汇报工单状态、处置计划、待答问题与审批。"),
    },
    "answer": {
        "name": bi("Clarification agent", "补充信息智能体"), "authority": "records_answer",
        "role": bi("Records your answer to an agent's question and re-runs the analysis.",
                   "记录你对智能体问题的回答，并触发重新分析。"),
    },
    "progress": {
        "name": bi("Progress agent", "项目进度智能体"), "authority": "read_only",
        "role": bi("Reports project progress, schedule variance and the next gate.",
                   "汇报项目进度、工期偏差与下一个关口。"),
    },
    "approvals": {
        "name": bi("Approval queue agent", "审批队列智能体"), "authority": "read_only",
        "role": bi("Lists what waits for approval; decisions stay with you.", "列出待审批事项；决定仍由你做。"),
    },
    "field": {
        "name": bi("Field report agent", "现场上报智能体"), "authority": "read_only",
        "role": bi("Reports the analysis of your recent field reports.", "汇报你最近现场上报的分析结果。"),
    },
}
AGENT_IDS: tuple[str, ...] = tuple(AGENTS)
WRITERS = {"intake", "answer"}
# Queues that should already include the work order this plan creates.
AFTER_INTAKE = {"approvals", "field"}
TOOL_AGENT = {
    "report_incident": "intake", "search_knowledge": "knowledge", "case_status": "case",
    "project_progress": "progress", "pending_approvals": "approvals",
}

DISPATCH_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "assistant_dispatch",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["steps", "reply"],
            "properties": {
                "reply": {"type": "string"},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["agent", "query", "case_id", "project_code", "question_id", "answer"],
                        "properties": {
                            "agent": {"type": "string", "enum": list(AGENT_IDS)},
                            "query": {"type": "string"},
                            "case_id": {"type": "string"},
                            "project_code": {"type": "string"},
                            "question_id": {"type": "integer"},
                            "answer": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
}

CASE_STATUS = {
    "NEEDS_PROJECT_CONFIRMATION": bi("waiting for project confirmation", "待确认项目归属"),
    "AWAITING_APPROVAL": bi("awaiting human approval", "等待人工审批"),
    "APPROVED": bi("approved, ready for the reply draft", "已批准，可生成回复草稿"),
    "EXECUTED": bi("draft generated, awaiting verification", "草稿已生成，等待独立核验"),
    "EXECUTION_FAILED": bi("draft generation failed", "草稿生成失败"),
    "VERIFIED": bi("verified, ready to close", "已核验，可关闭"),
    "VERIFICATION_FAILED": bi("verification failed", "核验未通过"),
    "CLOSED": bi("closed", "已关闭"),
    "REJECTED": bi("rejected, rework required", "已驳回，需返工"),
}

_THIS_CASE_RE = re.compile(
    r"(这个|该|此|那个|刚才的?|上面的?)(案例|工单|案子|问题单)|this (case|work order)|that (case|work order)|the same case",
    re.IGNORECASE)
_FIELD_RE = re.compile(r"我的上报|现场上报|上报记录|我上报的|field reports?|my reports?", re.IGNORECASE)
_LEAD = r"(?:然后|并且|并|再|同时|另外|还有|顺便|帮我|请|查一下|查查|查|看一下|看看|看|搜索|列出|告诉我|and |also |then )"
_SPLIT_RE = re.compile(r"[，,；;。！!？?\n]+\s*(?=" + _LEAD + ")", re.IGNORECASE)
_LEAD_RE = re.compile(r"^(?:然后|并且|并|再|同时|另外|还有|顺便|and|also|then)\s*", re.IGNORECASE)
_STEP_TAG_RE = re.compile(r"^S(\d)$")


class DispatchRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    session_id: str | None = Field(default=None, max_length=64)
    # Used only when there is no server-side session yet.
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    project_id: int | None = Field(default=None, gt=0)
    model_route: Literal["local", "openai", "auto"] | None = None
    data_classification: Literal["public", "internal", "restricted"] = "internal"


@dataclass
class Step:
    agent: str
    query: str = ""
    case_id: str | None = None      # "NEW": the work order created by this plan's intake step
    project_id: int | None = None
    question_id: int | None = None
    answer: str = ""

    def key(self) -> tuple:
        return (self.agent, self.query.lower() if self.agent == "knowledge" else "", self.case_id, self.project_id)


@dataclass
class PlanContext:
    project_codes: dict[str, int]
    known_case_ids: set[str]
    case_id: str | None = None                      # what "this case" refers to
    open_questions: dict[int, str] = field(default_factory=dict)  # of that case
    project_id: int | None = None


# --- planning -------------------------------------------------------------------

def _dedupe(steps: list[Step]) -> list[Step]:
    seen, unique = set(), []
    for step in steps:
        if step.key() not in seen:
            seen.add(step.key())
            unique.append(step)
    return unique[:MAX_STEPS]


def _clauses(text: str) -> list[str]:
    if len(text) > MAX_SPLIT_LENGTH:
        return [text]
    parts = [_LEAD_RE.sub("", part).strip() for part in _SPLIT_RE.split(text)]
    return [part for part in parts if part]


def dispatch_rules(message: str, ctx: PlanContext) -> list[Step]:
    """Deterministic planner: route every clause with the keyword rules.

    A single-clause message gets exactly the tool ``plan_rules`` picks. Any
    intake step receives the whole message (a letter needs its full context)
    and runs first; a clause the rules can only answer with help is dropped
    when other clauses carry a task.
    """
    text = message.strip()
    if ctx.case_id:
        text = _THIS_CASE_RE.sub(f" {ctx.case_id} ", text)
    # A long message that is not a question is a pasted letter or notice.
    if len(text) > MAX_SPLIT_LENGTH and not re.search(r"[?？]\s*$", text):
        return [Step("intake", query=message.strip(), project_id=plan_rules(text, ctx.project_codes, set())["project_id"])]
    steps: list[Step] = []
    for position, clause in enumerate(_clauses(text)):
        if _FIELD_RE.search(clause):
            steps.append(Step("field"))
            continue
        plan = plan_rules(clause, ctx.project_codes, ctx.known_case_ids)
        # A follow-on clause asking for rules ("then check the accident
        # reporting regulation") is a lookup even if it names an incident.
        if position > 0 and plan["tool"] == "report_incident" and _KNOWLEDGE_RE.search(clause):
            plan.update(tool="search_knowledge", query=clause)
        agent = TOOL_AGENT.get(plan["tool"])
        if agent == "intake":
            steps.insert(0, Step("intake", query=message.strip(), project_id=plan["project_id"]))
        elif agent:
            steps.append(Step(agent, query=plan["query"] or clause, case_id=plan["case_id"], project_id=plan["project_id"]))
    intakes = [s for s in steps if s.agent == "intake"]
    if len(intakes) > 1:
        steps = [intakes[0], *(s for s in steps if s.agent != "intake")]
    return _dedupe(steps)


def _plan_prompt(lang: str, ctx: PlanContext) -> str:
    language = "Simplified Chinese" if lang == "zh" else "English"
    roster = "\n".join(f"- {agent_id}: {spec['role']['en']}" for agent_id, spec in AGENTS.items())
    questions = "; ".join(f"[{qid}] {text}" for qid, text in ctx.open_questions.items()) or "none"
    return (
        "You are the dispatcher of GlobalInfra AI, an assistant for overseas transport infrastructure projects. "
        "Split the user's message into the tasks it asks for and assign each task to one sub-agent:\n"
        f"{roster}\n"
        "Rules:\n"
        f"- At most {MAX_STEPS} steps, in the order they should run. One step per distinct task; do not repeat a "
        "sub-agent for the same thing.\n"
        "- intake: the user reports a NEW site issue, incident, hazard, damage, delay or claim, or pastes an owner "
        "notice or letter. Put the full issue text in `query`. Use it at most once.\n"
        "- knowledge: questions on regulations, laws, standards, permits or contract clauses. Put a concise search "
        "query in `query`, keeping country and topic words.\n"
        "- case: status, plan, evidence or questions of an existing work order. Set `case_id` to an id from the "
        "message, the conversation or the current case, exactly as written, or to NEW for the work order created "
        "by an intake step earlier in this plan.\n"
        "- answer: ONLY when the user is answering one of the current case's open questions listed below. Set "
        "`question_id` to its id and copy the user's answer into `answer`.\n"
        "- progress: project progress or schedule. Set `project_code` when one project is meant.\n"
        "- approvals: what waits for approval, and any request to approve, reject, execute or close (you cannot do "
        "those; the list lets the user press the buttons).\n"
        "- field: the user's own recent field reports.\n"
        "- Greetings, thanks, questions about what you can do, or requests outside the platform: return no steps "
        f"and write `reply` in {language} (under 120 words). Never answer engineering, legal, contract or project "
        "facts yourself. Otherwise `reply` is an empty string.\n"
        "Unused fields are empty strings, and question_id is 0 when unused.\n"
        f"Known project codes: {', '.join(ctx.project_codes) or 'none'}.\n"
        f"Current case: {ctx.case_id or 'none'}. Its open questions: {questions}."
    )


def _plan_user(message: str, history: list[dict]) -> str:
    lines = [f"{turn['role']}: {turn['content']}" for turn in history[-PLANNER_HISTORY:]]
    transcript = "\n".join(lines) if lines else "(no earlier messages)"
    return f"Conversation so far:\n{transcript}\n\nCurrent user message:\n{message}"


def parse_dispatch(raw: str, ctx: PlanContext, message: str) -> tuple[list[Step], str | None] | None:
    """Validate a model plan against the roster, the database and the context."""
    match = _JSON_RE.search(raw or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        return None
    steps: list[Step] = []
    for item in data["steps"][:MAX_STEPS]:
        if not isinstance(item, dict) or item.get("agent") not in AGENTS:
            return None
        text = lambda key: str(item.get(key) or "").strip()  # noqa: E731
        step = Step(item["agent"], query=text("query"))
        code = text("project_code").upper()
        if code:
            if code not in ctx.project_codes:
                return None
            step.project_id = ctx.project_codes[code]
        if step.agent in {"knowledge", "intake"} and not step.query:
            step.query = message.strip()
        if step.agent in {"progress", "intake"} and step.project_id is None:
            step.project_id = _project_in_text(f"{step.query} {message}", ctx.project_codes)
        if step.agent == "intake" and any(s.agent == "intake" for s in steps):
            return None
        if step.agent == "case":
            case_id = text("case_id").upper()
            if case_id == "NEW":
                if not any(s.agent == "intake" for s in steps):
                    return None
            elif case_id not in ctx.known_case_ids:
                return None
            step.case_id = case_id
        if step.agent == "answer":
            question_id, answer = item.get("question_id"), text("answer")
            if not ctx.case_id or question_id not in ctx.open_questions or not answer or len(answer) > 4000:
                return None
            step.case_id, step.question_id, step.answer = ctx.case_id, question_id, answer
        steps.append(step)
    reply = str(data.get("reply") or "").strip()
    if not steps:
        if not reply or len(reply) > MAX_DIRECT_REPLY:
            return None
        return [], reply
    return _dedupe(steps), None


async def plan_dispatch(payload: DispatchRequest, lang: str, ctx: PlanContext,
                        history: list[dict]) -> tuple[list[Step], str | None, str]:
    rules = dispatch_rules(payload.message, ctx)
    if not _model_available(payload):
        return rules, None, "rules"
    try:
        raw = await generate(
            _plan_prompt(lang, ctx), _plan_user(payload.message, history),
            response_format=DISPATCH_FORMAT, route=payload.model_route, sensitivity=payload.data_classification,
        )
    except LLMError:
        return rules, None, "rules"
    parsed = parse_dispatch(raw, ctx, payload.message)
    if parsed is None:
        return rules, None, "rules"
    steps, reply = parsed
    # A reportable incident always reaches the governed intake path, even when
    # the model would only have answered or looked things up.
    rule_intake = next((s for s in rules if s.agent == "intake"), None)
    if rule_intake and _INCIDENT_RE.search(payload.message) and not any(s.agent == "intake" for s in steps):
        steps, reply = _dedupe([rule_intake, *steps]), None
    return steps, reply, "llm"


# --- sub-agents -------------------------------------------------------------------

@dataclass
class Dispatch:
    payload: DispatchRequest
    lang: str
    principal: Principal
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    case_ready: asyncio.Event = field(default_factory=asyncio.Event)
    new_case_id: str | None = None
    knowledge_answers: int = 0

    # ``_grounded_answer`` reads the route and sensitivity from its request.
    @property
    def model_route(self):
        return self.payload.model_route

    @property
    def data_classification(self):
        return self.payload.data_classification


def _t(lang: str, en: str, zh: str) -> str:
    return zh if lang == "zh" else en


class StepFailed(Exception):
    pass


async def _resolve_case(step: Step, run: Dispatch) -> str:
    if step.case_id != "NEW":
        return step.case_id
    await run.case_ready.wait()
    if not run.new_case_id:
        raise StepFailed(_t(run.lang, "The intake step did not create a work order.", "建案步骤没有生成工单。"))
    return run.new_case_id


async def agent_intake(step: Step, run: Dispatch, db: Session) -> dict:
    from .main import _intake_pipeline  # main imports this module's router

    project_id = run.payload.project_id or step.project_id
    try:
        if project_id is not None:
            require_project(run.principal, project_id)
        body = await _intake_pipeline(
            db, step.query, run.lang, raw_input_ref="assistant:dispatch", language_hint=None, source_file=None,
            model_route=run.payload.model_route, data_classification=run.payload.data_classification,
            organization_id=run.principal.organization_id, project_id_override=project_id,
        )
    except HTTPException as exc:
        raise StepFailed(str(exc.detail))
    run.new_case_id = body.get("case_id")
    intake = body.get("intake") or {}
    # The organization may add members to the core team; report who actually ran.
    trace = db.scalar(select(AgentTrace).where(AgentTrace.case_id == run.new_case_id, AgentTrace.kind == "team")
                      .order_by(AgentTrace.id.desc())) if run.new_case_id else None
    members = (trace.output or {}).get("team", []) if trace else []
    team = [localize(m["name"], run.lang) for m in members] or [agent["name"] for agent in body.get("specialist_team") or []]
    return {
        "summary": _t(run.lang,
                      f"Created work order {run.new_case_id} ({intake.get('case_type_label')}, risk {intake.get('risk')}); "
                      f"{len(team)} specialists analysed it.",
                      f"已建工单 {run.new_case_id}（{intake.get('case_type_label')}，风险 {intake.get('risk_label') or intake.get('risk')}），"
                      f"{len(team)} 个专家智能体完成分析。"),
        "case_id": run.new_case_id,
        "data": {
            "case_id": run.new_case_id, "case_type_label": intake.get("case_type_label"), "risk": intake.get("risk"),
            "risk_label": intake.get("risk_label"), "country_label": intake.get("country_label"),
            "stage": (intake.get("lifecycle_stage") or {}).get("name"), "deadline": intake.get("deadline"),
            "issues": intake.get("issues") or [], "team": team, "method": intake.get("classification_method"),
        },
    }


async def agent_knowledge(step: Step, run: Dispatch, db: Session) -> dict:
    hits = _search(db, step.query, run.payload.message)
    answer = None
    if hits and run.knowledge_answers < MAX_KNOWLEDGE_ANSWERS:
        run.knowledge_answers += 1
        answer = await _grounded_answer(step.query, hits, run.lang, run)
    refs = [doc.source_ref for _, doc in hits]
    if not hits:
        summary = _t(run.lang, f"No confident source for “{step.query}”.", f"知识库中没有与“{step.query}”足够相关的依据。")
    elif answer:
        summary = answer
    else:
        summary = _t(run.lang, f"Found {len(hits)} sources: {', '.join(refs)}.", f"找到 {len(hits)} 条依据：{'、'.join(refs)}。")
    return {
        "summary": summary, "refs": refs,
        "data": {"query": step.query, "hits": [_hit_payload(score, doc, run.lang) for score, doc in hits],
                 "answer": answer, "answer_method": "llm" if answer else "sources"},
    }


def _latest_plan(db: Session, case_id: str) -> list[dict]:
    run_id = db.scalar(select(AgentTrace.run_id).where(AgentTrace.case_id == case_id, AgentTrace.kind == "team")
                       .order_by(AgentTrace.id.desc()))
    if not run_id:
        return []
    planner = db.scalar(select(AgentTrace).where(AgentTrace.run_id == run_id, AgentTrace.kind == "planner"))
    return (planner.output or {}).get("steps", []) if planner else []


def open_questions(db: Session, case_id: str) -> dict[int, str]:
    rows = db.scalars(select(CaseInput).where(CaseInput.case_id == case_id, CaseInput.status == "OPEN").order_by(CaseInput.id))
    return {row.id: row.question for row in rows}


async def agent_case(step: Step, run: Dispatch, db: Session) -> dict:
    case_id = await _resolve_case(step, run)
    case = db.get(Case, case_id)
    if case is None:
        raise StepFailed(_t(run.lang, "Work order not found.", "未找到该工单。"))
    if case.project_id is not None:
        require_project(run.principal, case.project_id)
    actions = [s for s in _latest_plan(db, case_id) if not str(s.get("source", "")).startswith("governance")]
    questions = localize(open_questions(db, case_id), run.lang)
    pending = db.scalars(select(Approval).where(Approval.case_id == case_id, Approval.status == "PENDING")).all()
    first = None
    if actions:
        first = localize(actions[0]["text"], run.lang).rstrip("。.；; ")
        owner = localize(actions[0].get("owner_role") or "", run.lang)
        first += _t(run.lang, f" (owner: {owner})", f"（负责：{owner}）") if owner else ""
    status = localize(CASE_STATUS.get(case.status, bi(case.status)), run.lang)
    summary = _t(run.lang,
                 f"{case_id} is {status}, risk {case.risk}; {len(actions)} specialist actions"
                 f"{f', first: {first}' if first else ''}; {len(questions)} open questions; {len(pending)} pending approvals.",
                 f"{case_id} 当前{status}，风险 {case.risk}；专业处置动作 {len(actions)} 项"
                 f"{f'，首项：{first}' if first else ''}；待答问题 {len(questions)} 个；待审批 {len(pending)} 项。")
    return {"summary": summary, "case_id": case_id,
            "data": {"case_id": case_id, "status": case.status, "risk": case.risk,
                     "open_questions": [{"id": k, "question": v} for k, v in questions.items()],
                     "pending_approvals": len(pending)}}


async def agent_answer(step: Step, run: Dispatch, db: Session) -> dict:
    from .workflow import analyze_case  # workflow imports the agent organization

    if "platform_admin" not in run.principal.roles and not run.principal.roles & ANSWER_ROLES:
        raise StepFailed(_t(run.lang, "Your role cannot answer agent questions.", "当前角色不能回答智能体问题。"))
    row = db.get(CaseInput, step.question_id)
    if row is None or row.case_id != step.case_id or row.status != "OPEN":
        raise StepFailed(_t(run.lang, "That question is no longer open.", "该问题已不在待答状态。"))
    row.answer, row.status = step.answer, "ANSWERED"
    row.answered_by, row.answered_at = run.principal.subject, utc_now()
    db.commit()
    frozen = db.scalar(select(ExecutionReceipt).where(ExecutionReceipt.case_id == step.case_id)) is not None
    if not frozen:
        await analyze_case(db, step.case_id)
    question = localize(row.question, run.lang)
    return {
        "summary": _t(run.lang,
                      f"Recorded the answer to “{question}”" + ("" if frozen else " and re-ran the analysis") + ".",
                      f"已记录对“{question}”的回答" + ("" if frozen else "，并重新分析") + "。"),
        "case_id": step.case_id,
        "data": {"case_id": step.case_id, "question": question, "answer": step.answer, "reanalyzed": not frozen},
    }


async def agent_progress(step: Step, run: Dispatch, db: Session) -> dict:
    project_id = step.project_id or run.payload.project_id
    rows = []
    for project in db.scalars(select(Project).order_by(Project.id)):
        if (project_id and project.id != project_id) or not run.principal.can_access_project(project.id):
            continue
        info = PROJECT_INTELLIGENCE.get(project.id, {})
        rows.append(localize({
            "id": project.id, "code": project.code, "progress": info.get("progress"),
            "schedule_variance": info.get("schedule_variance"), "next_gate": info.get("next_gate"),
            "gate_date": info.get("gate_date"), "risk_level": project.risk_level,
        }, run.lang))
    lines = [
        _t(run.lang, f"{r['code']} {r['progress']}% (variance {r['schedule_variance']} d, next gate {r['next_gate']} {r['gate_date']})",
           f"{r['code']} 进度 {r['progress']}%（偏差 {r['schedule_variance']} 天，下一关口 {r['next_gate']} {r['gate_date']}）")
        for r in rows if r["progress"] is not None
    ]
    return {"summary": "; ".join(lines) or _t(run.lang, "No project in scope.", "没有可查看的项目。"),
            "data": {"project_ids": [r["id"] for r in rows], "projects": rows}}


async def agent_approvals(step: Step, run: Dispatch, db: Session) -> dict:
    rows = [a for a in db.scalars(select(Approval).where(Approval.status == "PENDING").order_by(Approval.created_at.desc()))]
    top = [localize({"id": a.id, "case_id": a.case_id, "title": a.title, "approver_role": a.approver_role, "risk": a.risk}, run.lang)
           for a in rows[:5]]
    critical = sum(1 for a in rows if a.risk in {"HIGH", "CRITICAL"})
    return {"summary": _t(run.lang, f"{len(rows)} approvals pending, {critical} of them high or critical risk.",
                          f"待审批 {len(rows)} 项，其中高或紧急风险 {critical} 项。"),
            "data": {"count": len(rows), "top": top}}


async def agent_field(step: Step, run: Dispatch, db: Session) -> dict:
    from .field_ai import report_payload

    rows = db.scalars(select(FieldObservation).where(
        FieldObservation.organization_id == run.principal.organization_id,
        FieldObservation.reporter_id == run.principal.subject,
    ).order_by(FieldObservation.captured_at.desc()).limit(5))
    reports = []
    for row in rows:
        report = localize(report_payload(db, row), run.lang)
        reports.append({
            "id": report["id"], "description": report["description"][:120], "status": report["analysis_status"],
            "risk": report["risk_review"]["final"], "case_id": report["case_id"],
            "open_questions": sum(1 for q in report["questions"] if q["status"] == "OPEN"),
        })
    waiting = sum(r["open_questions"] for r in reports)
    return {"summary": _t(run.lang, f"{len(reports)} recent field reports; {waiting} agent questions wait for you.",
                          f"最近 {len(reports)} 条现场上报；有 {waiting} 个智能体问题等你回答。"),
            "data": {"reports": reports}}


RUNNERS = {
    "intake": agent_intake, "knowledge": agent_knowledge, "case": agent_case, "answer": agent_answer,
    "progress": agent_progress, "approvals": agent_approvals, "field": agent_field,
}


async def run_step(index: int, step: Step, run: Dispatch, emit) -> dict:
    if step.agent in AFTER_INTAKE:
        await run.case_ready.wait()
    await emit({"type": "step_start", "index": index})
    db = SessionLocal()
    try:
        async def work():
            if step.agent in WRITERS:
                async with run.write_lock:
                    return await RUNNERS[step.agent](step, run, db)
            return await RUNNERS[step.agent](step, run, db)
        result = {"status": "ok", **await asyncio.wait_for(work(), STEP_TIMEOUT_S)}
    except StepFailed as exc:
        result = {"status": "error", "summary": str(exc)}
    except HTTPException as exc:
        result = {"status": "error", "summary": str(exc.detail)}
    except Exception as exc:  # one failed step (model, timeout, data) never sinks the others
        log.exception("dispatch step %s (%s) failed", index, step.agent)
        db.rollback()
        result = {"status": "error", "summary": _t(run.lang, f"The step failed: {type(exc).__name__}.", f"该步骤失败：{type(exc).__name__}。")}
    finally:
        db.close()
        if step.agent == "intake":
            run.case_ready.set()
    await emit({"type": "step_done", "index": index, **result})
    return result


# --- summary ----------------------------------------------------------------------

def fallback_summary(steps: list[Step], results: list[dict], lang: str) -> str:
    return "\n".join(
        f"S{i + 1} {localize(AGENTS[s.agent]['name'], lang)}：{r['summary']}" for i, (s, r) in enumerate(zip(steps, results))
    )


def validate_summary(text: str, step_count: int, refs: set[str]) -> bool:
    cited = {c.strip() for c in _CITATION_RE.findall(text)}
    tags = {int(m.group(1)) for c in cited if (m := _STEP_TAG_RE.match(c))}
    others = {c for c in cited if not _STEP_TAG_RE.match(c)}
    return bool(tags) and all(1 <= t <= step_count for t in tags) and others <= refs


async def summarise(steps: list[Step], results: list[dict], run: Dispatch) -> tuple[str, str]:
    fallback = fallback_summary(steps, results, run.lang)
    if not _model_available(run.payload):
        return fallback, "rules"
    language = "Simplified Chinese" if run.lang == "zh" else "English"
    facts = "\n".join(f"[S{i + 1}] {AGENTS[s.agent]['name']['en']} ({r['status']}): {r['summary']}"
                      for i, (s, r) in enumerate(zip(steps, results)))
    refs = {ref for r in results for ref in r.get("refs", [])}
    system = (
        "You summarise for the user what the sub-agents just did, using ONLY their results below. End every "
        "sentence with the step tag it relies on in square brackets, e.g. [S1]; you may also cite a source "
        "reference that a result names, e.g. [MY-HSE-WAH-01]. Do not add facts, numbers or obligations. Say "
        "plainly when a step failed or found nothing. Point out what needs the user's decision or answer next. "
        f"Write in {language}, under 120 words, as 2-4 short sentences."
    )
    try:
        text = (await generate(system, f"User message: {run.payload.message[:1500]}\n\nResults:\n{facts}",
                               route=run.payload.model_route, sensitivity=run.payload.data_classification)).strip()
    except LLMError:
        return fallback, "rules"
    return (text, "llm") if validate_summary(text, len(steps), refs) else (fallback, "rules")


# --- session memory ---------------------------------------------------------------

def load_session(db: Session, session_id: str | None, principal: Principal) -> AssistantSession:
    session = db.get(AssistantSession, session_id) if session_id else None
    if session is None or session.subject != principal.subject or session.organization_id != principal.organization_id:
        session = AssistantSession(id=uuid.uuid4().hex, organization_id=principal.organization_id,
                                   subject=principal.subject, turns=[], context={})
        db.add(session)
        db.flush()
    return session


def build_context(db: Session, payload: DispatchRequest, session: AssistantSession, history: list[dict]) -> PlanContext:
    project_codes = {code.upper(): pid for pid, code in db.execute(select(Project.id, Project.code))}
    current = (session.context or {}).get("case_id")
    mentioned = {m.upper() for m in _CASE_ID_RE.findall(" ".join([payload.message, *(t["content"] for t in history)]))}
    if current:
        mentioned.add(current)
    known = set(db.scalars(select(Case.id).where(Case.id.in_(mentioned)))) if mentioned else set()
    current = current if current in known else None
    questions = {k: localize(v, "en") for k, v in open_questions(db, current).items()} if current else {}
    return PlanContext(project_codes=project_codes, known_case_ids=known, case_id=current, open_questions=questions,
                       project_id=payload.project_id or (session.context or {}).get("project_id"))


def remember(db: Session, session_id: str, message: str, reply: str, steps: list[Step], results: list[dict],
             project_id: int | None) -> None:
    session = db.get(AssistantSession, session_id)
    if session is None:
        return
    context = dict(session.context or {})
    for step, result in zip(steps, results):
        if result.get("case_id"):
            context["case_id"] = result["case_id"]
        if step.project_id:
            context["project_id"] = step.project_id
    if project_id:
        context["project_id"] = project_id
    turns = [*(session.turns or []), {"role": "user", "content": message[:2000]}, {"role": "assistant", "content": reply[:2000]}]
    session.turns, session.context, session.updated_at = turns[-MAX_TURNS:], context, utc_now()
    db.commit()


# --- endpoint ---------------------------------------------------------------------

def _step_view(index: int, step: Step, lang: str) -> dict:
    return localize({
        "index": index, "agent": step.agent, "name": AGENTS[step.agent]["name"], "authority": AGENTS[step.agent]["authority"],
        "query": step.query if step.agent in {"knowledge"} else "", "case_id": step.case_id,
        "project_id": step.project_id, "question_id": step.question_id,
    }, lang)


async def dispatch(payload: DispatchRequest, lang: str, principal: Principal, emit) -> None:
    db = SessionLocal()
    try:
        session = load_session(db, payload.session_id, principal)
        history = list(session.turns or []) or [t.model_dump() for t in payload.history]
        ctx = build_context(db, payload, session, history)
        session_id = session.id
        db.commit()
    finally:
        db.close()
    await emit({"type": "session", "session_id": session_id, "context_case_id": ctx.case_id})

    steps, reply, method = await plan_dispatch(payload, lang, ctx, history)
    await emit({"type": "plan", "method": method, "steps": [_step_view(i, s, lang) for i, s in enumerate(steps)]})

    results: list[dict] = []
    summary_method = None
    if steps:
        run = Dispatch(payload, lang, principal)
        if not any(s.agent == "intake" for s in steps):
            run.case_ready.set()
        results = list(await asyncio.gather(*(run_step(i, s, run, emit) for i, s in enumerate(steps))))
        if len(steps) > 1:
            reply, summary_method = await summarise(steps, results, run)
            await emit({"type": "summary", "text": reply, "method": summary_method})
        else:
            reply = results[0]["summary"]
    else:
        reply = reply or ""
        await emit({"type": "reply", "text": reply or None})

    db = SessionLocal()
    try:
        remember(db, session_id, payload.message, reply or "", steps, results, payload.project_id)
    finally:
        db.close()
    await emit({"type": "done"})


@router.post("/dispatch")
async def dispatch_endpoint(
    payload: DispatchRequest, lang: str = Depends(get_lang), principal: Principal = Depends(get_principal),
):
    if payload.project_id is not None:
        require_project(principal, payload.project_id)
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: dict) -> None:
        await queue.put(event)

    async def run() -> None:
        try:
            await dispatch(payload, lang, principal, emit)
        except Exception as exc:  # the stream must always end with an event the client understands
            log.exception("dispatch failed")
            await queue.put({"type": "error", "message": str(exc) or type(exc).__name__})
        finally:
            await queue.put(None)

    async def stream():
        task = asyncio.create_task(run())
        try:
            while (event := await queue.get()) is not None:
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        finally:
            await task

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"cache-control": "no-cache"})


@router.get("/agents")
def dispatch_agents(lang: str = Depends(get_lang)):
    """The dispatcher's sub-agents; the case agent convenes the specialist organization."""
    return localize([{"id": k, **v} for k, v in AGENTS.items()], lang)


@router.get("/sessions/{session_id}")
def session_context(session_id: str, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    session = db.get(AssistantSession, session_id)
    if session is None or session.subject != principal.subject or session.organization_id != principal.organization_id:
        raise HTTPException(404, "Session not found")
    return {"session_id": session.id, "context": session.context, "turns": session.turns}
