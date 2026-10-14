"""Conversational assistant: an LLM router over the platform's governed tools.

``POST /assistant/chat`` is the backend of the web app's Assistant page. It
does not add a new reasoning engine and never acts on its own authority:

1. **Plan.** When a model is configured for the request's route/sensitivity,
   the model picks exactly one tool from ``TOOLS`` (a schema-constrained enum,
   same structured-output pattern as ``llm_classify``) and fills its
   arguments. Case ids and project codes it returns must exist in the
   database. Anything malformed, out of vocabulary or unverifiable falls back
   to the deterministic keyword planner, which is also the only planner when
   no model is configured -- so offline/CI behaviour stays deterministic.
2. **Act through existing capabilities.** Knowledge questions run the same
   TF-IDF retrieval as ``/knowledge/search``; incident reports, work-order
   status, progress and approvals are executed by the client through the
   existing endpoints (intake, case detail, projects, approvals), so their
   governance and role checks are unchanged.
3. **Answer only from evidence.** A knowledge answer is composed by the model
   strictly from the retrieved sources and must cite them; an answer that
   cites nothing, or cites a source that was not retrieved, is discarded in
   favour of the plain source list. Below the workflow's confident relevance
   threshold the assistant declines instead of answering.

Approvals, execution, verification and closure are deliberately not tools:
they stay explicit human button actions.
"""
from __future__ import annotations

import json
import re
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .i18n import get_lang, localize
from .llm import LLMError, generate, is_llm_configured, reset_routing_trace, routing_trace
from .models import Case, KnowledgeDocument, Project
from .retrieval import KnowledgeIndex
from .security import Principal, get_principal, require_project
from .workflow import CONFIDENT_RELEVANCE

router = APIRouter(prefix="/assistant", tags=["assistant"])

TOOLS: tuple[str, ...] = (
    "report_incident", "search_knowledge", "case_status",
    "project_progress", "pending_approvals", "answer_directly",
)
MAX_HISTORY = 8
MAX_DIRECT_REPLY = 1500
KNOWLEDGE_TOP_K = 5

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_CASE_ID_RE = re.compile(r"\bCASE-[A-Z0-9][A-Z0-9-]*\b", re.IGNORECASE)
_CITATION_RE = re.compile(r"\[([^\[\]]+)\]")

# Deterministic planner vocabulary (mirrors the web client's fallback rules).
_HELP_RE = re.compile(
    r"^(你好|您好|嗨|hi|hello|hey)[!！。,， ]*$|你能做什么|你会做什么|你会什么|你是谁|能帮我做什么|怎么用|使用说明|"
    r"^帮助$|^help$|what can you do|who are you|how do i use", re.IGNORECASE)
_INCIDENT_RE = re.compile(
    r"通知|整改|事故|隐患|损坏|破损|延误|索赔|违规|泄漏|坍塌|受伤|缺陷|"
    r"notice|incident|damage|delay|claim|injur|defect|rectif|hazard|unsafe|leak", re.IGNORECASE)
_APPROVAL_RE = re.compile(r"审批|待我|批准|approval|approve|sign[- ]?off", re.IGNORECASE)
_PROGRESS_RE = re.compile(r"进度|进展|状态|概况|progress|status|schedule|overview", re.IGNORECASE)
_KNOWLEDGE_RE = re.compile(
    r"法规|法律|规定|规范|标准|条款|条例|要求|依据|哪一条|regulation|law|clause|requirement|standard|permit",
    re.IGNORECASE)

PLAN_FORMAT: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "assistant_plan",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["tool", "query", "case_id", "project_code", "reply"],
            "properties": {
                "tool": {"type": "string", "enum": list(TOOLS)},
                "query": {"type": "string"},
                "case_id": {"type": "string"},
                "project_code": {"type": "string"},
                "reply": {"type": "string"},
            },
        },
    },
}


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class AssistantChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    project_id: int | None = Field(default=None, gt=0)
    model_route: Literal["local", "openai", "auto"] | None = None
    data_classification: Literal["public", "internal", "restricted"] = "internal"
    # Set by the client's quick-action buttons: the user chose the tool, so
    # no planning is needed (method "user").
    tool: Literal["report_incident", "search_knowledge", "project_progress", "pending_approvals"] | None = None


def plan_rules(message: str, project_codes: dict[str, int], known_case_ids: set[str]) -> dict:
    """Deterministic keyword planner; the fallback for every LLM failure."""
    text = message.strip()
    project_id = _project_in_text(text, project_codes)
    incident = bool(_INCIDENT_RE.search(text))
    plan = {"tool": "report_incident", "query": "", "case_id": None, "project_id": project_id, "reply": None}
    case_id = next((m.upper() for m in _CASE_ID_RE.findall(text) if m.upper() in known_case_ids), None)
    if len(text) <= 30 and _HELP_RE.search(text):
        plan["tool"] = "answer_directly"
    elif case_id and not incident:
        plan.update(tool="case_status", case_id=case_id)
    elif not incident and _APPROVAL_RE.search(text) and len(text) <= 40:
        plan["tool"] = "pending_approvals"
    elif not incident and _PROGRESS_RE.search(text) and len(text) <= 60:
        plan["tool"] = "project_progress"
    elif not incident and (_KNOWLEDGE_RE.search(text) or re.search(r"[?？]\s*$", text)):
        plan.update(tool="search_knowledge", query=text)
    elif len(text) < 8:
        plan["tool"] = "answer_directly"
    return plan


def _project_in_text(text: str, project_codes: dict[str, int]) -> int | None:
    upper = text.upper()
    return next((pid for code, pid in project_codes.items() if code in upper), None)


def _plan_prompt(lang: str, project_codes: dict[str, int]) -> str:
    language = "Simplified Chinese" if lang == "zh" else "English"
    return (
        "You route messages for GlobalInfra AI, an assistant for overseas transport infrastructure "
        "projects (rail, highway, bridge, port, airport). Pick exactly one tool:\n"
        "- report_incident: the user reports a new site issue, incident, hazard, damage, delay, claim, "
        "or pastes an owner notice/letter that needs a work order.\n"
        "- search_knowledge: questions about regulations, laws, standards, permits, contract clauses or "
        "requirements. Put a concise search query in `query`, keeping country and topic words.\n"
        "- case_status: the user asks about an existing work order. Set `case_id` to a work-order id that "
        "appears in the message or the conversation, exactly as written.\n"
        "- project_progress: progress, schedule or status of projects. Set `project_code` when one project "
        f"is meant; known codes: {', '.join(project_codes) or 'none'}.\n"
        "- pending_approvals: what is waiting for approval, and any request to approve, reject, execute or "
        "close things (you cannot do those yourself; the list lets the user press the buttons).\n"
        "- answer_directly: ONLY greetings, questions about what you can do or how to use the assistant, "
        "thanks, or requests outside the platform's scope. Never answer engineering, legal, contract or "
        "project facts yourself: route those to a tool.\n"
        f"For answer_directly write `reply` in {language} (under 120 words). You can: turn a site issue or "
        "owner letter (text or PDF/Word/TXT) into a work order with evidence-backed specialist analysis; "
        "search local regulations and the knowledge base with citations; report project progress; list "
        "pending approvals; and walk a work order through human approval, draft generation, independent "
        "verification and closure. Approvals and execution always need the user to press the buttons; "
        "you never approve, send or execute anything yourself. Mention only the capabilities listed here; "
        "never offer anything else. For out-of-scope requests say briefly what you can help with instead.\n"
        "For every other tool set `reply` to an empty string. Unused fields are empty strings."
    )


def _plan_user(message: str, history: list[ChatTurn]) -> str:
    lines = [f"{turn.role}: {turn.content}" for turn in history[-MAX_HISTORY:]]
    transcript = "\n".join(lines) if lines else "(no earlier messages)"
    return f"Conversation so far:\n{transcript}\n\nCurrent user message:\n{message}"


def _parse_plan(raw: str, project_codes: dict[str, int], known_case_ids: set[str]) -> dict | None:
    """Validate a model plan against the tool vocabulary and the database."""
    match = _JSON_RE.search(raw or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("tool") not in TOOLS:
        return None
    tool = data["tool"]
    text_field = lambda key: str(data.get(key) or "").strip()  # noqa: E731
    plan = {"tool": tool, "query": text_field("query"), "case_id": None, "project_id": None, "reply": None}
    code = text_field("project_code").upper()
    if code:
        if code not in project_codes:
            return None
        plan["project_id"] = project_codes[code]
    if tool == "case_status":
        case_id = text_field("case_id").upper()
        if case_id not in known_case_ids:
            return None
        plan["case_id"] = case_id
    if tool == "answer_directly":
        reply = text_field("reply")
        if not reply or len(reply) > MAX_DIRECT_REPLY:
            return None
        plan["reply"] = reply
    return plan


def _model_available(payload: AssistantChatRequest) -> bool:
    """True when a model may serve this request; a disallowed route (e.g.
    restricted data with an explicit cloud route) means "no model", never an
    error, so the assistant degrades to its deterministic path."""
    try:
        return is_llm_configured(payload.model_route, payload.data_classification)
    except LLMError:
        return False


async def _plan(payload: AssistantChatRequest, lang: str, project_codes: dict[str, int],
                known_case_ids: set[str]) -> tuple[dict, str]:
    rules = plan_rules(payload.message, project_codes, known_case_ids)
    if not _model_available(payload):
        return rules, "rules"
    try:
        raw = await generate(
            _plan_prompt(lang, project_codes), _plan_user(payload.message, payload.history),
            response_format=PLAN_FORMAT, route=payload.model_route, sensitivity=payload.data_classification,
        )
    except LLMError:
        return rules, "rules"
    plan = _parse_plan(raw, project_codes, known_case_ids)
    if plan is None:
        return rules, "rules"
    # A message the rules recognise as a reportable incident is never brushed
    # off with a chat reply: it must reach the governed intake path.
    if plan["tool"] == "answer_directly" and rules["tool"] == "report_incident" and _INCIDENT_RE.search(payload.message):
        return rules, "rules"
    if plan["project_id"] is None:
        plan["project_id"] = rules["project_id"]
    return plan, "llm"


def _search(db: Session, *queries: str) -> list[tuple[float, KnowledgeDocument]]:
    """Search with every query and keep each document's best score.

    The user's own words are always one of the queries, so a model-rewritten
    query (e.g. translated, or phrased differently from the corpus) can add
    hits but never lose the ones the original wording finds.
    """
    docs = [doc for doc in db.scalars(select(KnowledgeDocument)) if doc.status == "CURRENT"]
    index = KnowledgeIndex(docs)
    best: dict[int, tuple[float, KnowledgeDocument]] = {}
    for query in dict.fromkeys(q for q in queries if q and q.strip()):
        for score, doc in index.search(query, top_k=KNOWLEDGE_TOP_K):
            if score >= CONFIDENT_RELEVANCE and score > best.get(doc.id, (0.0, None))[0]:
                best[doc.id] = (score, doc)
    return sorted(best.values(), key=lambda item: item[0], reverse=True)[:KNOWLEDGE_TOP_K]


def _hit_payload(score: float, doc: KnowledgeDocument, lang: str) -> dict:
    return localize({
        "id": doc.id, "title": doc.title, "source_ref": doc.source_ref, "jurisdiction": doc.jurisdiction,
        "version": doc.version, "summary": doc.summary, "relevance": round(score, 4),
    }, lang)


def _validate_answer(answer: str, refs: set[str]) -> bool:
    cited = {ref.strip() for ref in _CITATION_RE.findall(answer)}
    return bool(cited) and cited <= refs


async def _grounded_answer(question: str, hits: list[tuple[float, KnowledgeDocument]], lang: str,
                           payload: AssistantChatRequest) -> str | None:
    """Compose an answer strictly from retrieved sources, or return None."""
    if not hits or not _model_available(payload):
        return None
    language = "Simplified Chinese" if lang == "zh" else "English"
    sources = "\n\n".join(
        f"[{doc.source_ref}] {localize(doc.title, lang)}\n{localize(doc.summary, lang)}\n{localize(doc.content, lang)[:1200]}"
        for _, doc in hits
    )
    system = (
        "Answer the user's question using ONLY the sources provided. Cite every statement with the "
        "source reference in square brackets exactly as given, e.g. [MY-HSE-WAH-01]. If the sources do "
        "not answer the question, say that the knowledge base does not cover it. Do not add obligations, "
        "numbers or clauses that are not in the sources. Remind the user that legal obligations must be "
        f"confirmed by the competent authority. Write in {language}, under 150 words."
    )
    try:
        answer = (await generate(system, f"Question: {question}\n\nSources:\n{sources}",
                                 route=payload.model_route, sensitivity=payload.data_classification)).strip()
    except LLMError:
        return None
    refs = {doc.source_ref for _, doc in hits}
    return answer if _validate_answer(answer, refs) else None


@router.post("/chat")
async def chat(
    payload: AssistantChatRequest,
    db: Session = Depends(get_db),
    lang: str = Depends(get_lang),
    principal: Principal = Depends(get_principal),
):
    reset_routing_trace()
    if payload.project_id is not None:
        require_project(principal, payload.project_id)
    project_codes = {code.upper(): pid for pid, code in db.execute(select(Project.id, Project.code))}
    mentioned = {m.upper() for m in _CASE_ID_RE.findall(" ".join([payload.message, *(t.content for t in payload.history)]))}
    known_case_ids = set(db.scalars(select(Case.id).where(Case.id.in_(mentioned)))) if mentioned else set()

    if payload.tool:
        plan = plan_rules(payload.message, project_codes, known_case_ids)
        plan.update(tool=payload.tool, query=payload.message, case_id=None, reply=None)
        method = "user"
    else:
        plan, method = await _plan(payload, lang, project_codes, known_case_ids)
    if plan["project_id"] is not None:
        require_project(principal, plan["project_id"])
    result = {
        "tool": plan["tool"], "method": method, "reply": plan["reply"], "case_id": plan["case_id"],
        "project_id": plan["project_id"] or payload.project_id, "query": None, "hits": None, "answer_method": None,
    }
    if plan["tool"] == "search_knowledge":
        query = plan["query"] or payload.message
        hits = _search(db, query, payload.message)
        answer = await _grounded_answer(payload.message, hits, lang, payload)
        result.update(
            query=query, hits=[_hit_payload(score, doc, lang) for score, doc in hits],
            reply=answer, answer_method="llm" if answer else "sources",
        )
    result["model_routing"] = {
        "requested": payload.model_route, "data_classification": payload.data_classification,
        "trace": routing_trace(),
    }
    return result
