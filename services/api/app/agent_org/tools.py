"""Tools agents can actually call.

Every tool reads data the platform already holds (knowledge base, cases,
project portfolio, digital twin, country packs) and returns a JSON-safe
record that is stored in the agent trace. Tools never write business data
and never invent numbers: when the inputs are not there, the output says so
and the agent records a gap or asks a human.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain import PROJECT_INTELLIGENCE
from ..i18n import bi
from ..models import Case, CountryPack, KnowledgeDocument, Project, TwinObject
from ..retrieval import KnowledgeIndex, tokenize
from .cards import AgentCard

# Relevance thresholds for TF-IDF cosine scores, calibrated against the
# seeded knowledge base: below MIN nothing is cited; between MIN and
# CONFIDENT a hit is recorded as a gap; at or above CONFIDENT it is evidence.
MIN_RELEVANCE = 0.05
CONFIDENT_RELEVANCE = 0.22
TOP_K_EVIDENCE = 2

RESOLVED_STATUSES = ("CLOSED", "VERIFIED", "EXECUTED")
_ELEMENT_RE = re.compile(r"\b([PS]\d{1,3}|ST\d{2}|BRG\d{1,3}[A-Z]?|AHU\d{2})\b", re.IGNORECASE)
_EOT_RE = re.compile(
    r"extension of time(?: of)?\s*(\d+)\s*days?|(\d+)\s*days?\s*(?:of\s*)?(?:extension|eot)|工期延长\s*(\d+)\s*天|延长工期\s*(\d+)\s*天",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(r"\b(RM|MYR|USD|US\$|IDR|SAR|AED)\s?([\d,]+(?:\.\d+)?)", re.IGNORECASE)
_QUANTITY_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(nos|no\.|bolts|units|pcs|m3|m²|m2|tonnes|tons|t)\b", re.IGNORECASE)


@dataclass
class ToolContext:
    db: Session
    case: Case
    project: Project | None
    country: str | None
    stage: str
    base_query: str
    answers: list[str] = field(default_factory=list)
    full_text: str = ""
    index: KnowledgeIndex | None = None

    @property
    def text(self) -> str:
        """Full source text (the case description is truncated) for pattern tools."""
        return self.full_text or self.base_query

    def knowledge_index(self) -> KnowledgeIndex:
        if self.index is None:
            # The whole corpus keeps relevance scores stable; jurisdiction is
            # filtered on the ranked results instead.
            self.index = KnowledgeIndex(list(self.db.scalars(select(KnowledgeDocument))))
        return self.index

    def in_jurisdiction(self, doc) -> bool:
        return not self.country or not doc.country_code or doc.country_code == self.country


@dataclass
class ToolResult:
    tool: str
    ok: bool
    output: dict
    summary: dict
    hits: list = field(default_factory=list)  # (score, KnowledgeDocument) for knowledge.search only

    def record(self) -> dict:
        return {"tool": self.tool, "ok": self.ok, "output": self.output, "summary": self.summary}


def _text(value) -> str:
    if isinstance(value, dict):
        return value.get("en") or next(iter(value.values()), "")
    return value or ""


def knowledge_search(ctx: ToolContext, card: AgentCard, extra_query: str = "") -> ToolResult:
    query = " ".join(part for part in (
        ctx.base_query, card.focus_terms, card.country_terms.get(ctx.country or "", ""),
        " ".join(ctx.answers), extra_query,
    ) if part)
    ranked = ctx.knowledge_index().search(query, top_k=TOP_K_EVIDENCE + 8)
    hits = [(score, doc) for score, doc in ranked if score >= MIN_RELEVANCE and ctx.in_jurisdiction(doc)][:TOP_K_EVIDENCE]
    output = {"hits": [
        {"source_ref": doc.source_ref, "title": doc.title, "score": round(score, 4), "country": doc.country_code}
        for score, doc in hits
    ], "country_scope": ctx.country}
    refs = ", ".join(doc.source_ref for _, doc in hits) or "none"
    return ToolResult("knowledge.search", bool(hits), output,
                      bi(f"Retrieved {len(hits)} source(s): {refs}.", f"检索到 {len(hits)} 条来源：{refs}。"), hits)


def case_precedents(ctx: ToolContext, card: AgentCard) -> ToolResult:
    case_type = _text(ctx.case.type)
    own = set(tokenize(ctx.base_query))
    candidates = []
    for other in ctx.db.scalars(select(Case).where(Case.id != ctx.case.id, Case.status.in_(RESOLVED_STATUSES))):
        if _text(other.type) != case_type:
            continue
        theirs = set(tokenize(" ".join([_text(other.title), _text(other.description)])))
        if not own or not theirs:
            continue
        similarity = len(own & theirs) / len(own | theirs)
        if similarity >= 0.08:
            candidates.append((similarity, other))
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    rows = [{"case_id": c.id, "title": c.title, "status": c.status, "similarity": round(s, 3)} for s, c in candidates[:2]]
    ids = ", ".join(row["case_id"] for row in rows) or "none"
    return ToolResult("case.precedents", bool(rows), {"precedents": rows},
                      bi(f"Found {len(rows)} resolved similar case(s): {ids}.", f"找到 {len(rows)} 个已办结的相似案例：{ids}。"))


def project_status(ctx: ToolContext, card: AgentCard) -> ToolResult:
    if ctx.project is None:
        return ToolResult("project.status", False, {"reason": "case not routed to a project"},
                          bi("No project is confirmed for this case.", "该案例尚未确认项目。"))
    intel = PROJECT_INTELLIGENCE.get(ctx.project.id, {})
    output = {
        "project": ctx.project.code, "phase": intel.get("phase"), "progress": intel.get("progress"),
        "schedule_variance_days": intel.get("schedule_variance"), "next_gate": intel.get("next_gate"),
        "gate_date": intel.get("gate_date"), "budget_m": intel.get("budget"), "forecast_m": intel.get("forecast"),
    }
    variance = intel.get("schedule_variance")
    return ToolResult("project.status", True, output, bi(
        f"{ctx.project.code}: {intel.get('progress')}% complete, schedule variance {variance} days, next gate {_text(intel.get('next_gate'))} on {intel.get('gate_date')}.",
        f"{ctx.project.code}：完成 {intel.get('progress')}%，工期偏差 {variance} 天，下一关口 {(intel.get('next_gate') or {}).get('zh', '')}（{intel.get('gate_date')}）。",
    ))


def twin_locate(ctx: ToolContext, card: AgentCard) -> ToolResult:
    tokens = sorted({match.upper() for match in _ELEMENT_RE.findall(ctx.text)})
    if ctx.project is None or not tokens:
        return ToolResult("twin.locate", False, {"elements": tokens},
                          bi("No twin element reference found in the case.", "案例中未找到可定位的孪生构件编号。"))
    found = []
    for obj in ctx.db.scalars(select(TwinObject).where(TwinObject.project_id == ctx.project.id)):
        if any(obj.id.upper().endswith(f"-{token}") for token in tokens):
            found.append({"twin_id": obj.id, "name": obj.name, "status": obj.status,
                          "health_score": obj.health_score, "progress": obj.progress})
    ids = ", ".join(item["twin_id"] for item in found) or "none"
    return ToolResult("twin.locate", bool(found), {"elements": tokens, "objects": found},
                      bi(f"Located twin object(s): {ids}.", f"定位到孪生对象：{ids}。"))


def permit_gates(ctx: ToolContext, card: AgentCard) -> ToolResult:
    pack = ctx.db.get(CountryPack, ctx.country) if ctx.country else None
    if pack is None:
        return ToolResult("permit.gates", False, {"country": ctx.country},
                          bi("No country pack applies to this case.", "该案例没有适用的国家包。"))
    gates = [
        {"code": p["code"], "name": p["name"], "authority": p["authority"], "gate": p["gate"], "evidence": p["evidence"]}
        for p in pack.permit_catalog or [] if ctx.stage in (p.get("stages") or [])
    ]
    codes = ", ".join(g["code"] for g in gates) or "none"
    return ToolResult("permit.gates", bool(gates), {"country": ctx.country, "stage": ctx.stage, "gates": gates},
                      bi(f"{len(gates)} permit gate(s) apply at the {ctx.stage} stage: {codes}.", f"{ctx.stage} 阶段适用 {len(gates)} 个许可关卡：{codes}。"))


def schedule_impact(ctx: ToolContext, card: AgentCard) -> ToolResult:
    match = _EOT_RE.search(ctx.text)
    eot = next((int(group) for group in match.groups() if group), None) if match else None
    intel = PROJECT_INTELLIGENCE.get(ctx.project.id, {}) if ctx.project else {}
    variance = intel.get("schedule_variance")
    output = {"eot_requested_days": eot, "response_deadline": ctx.case.deadline,
              "project_schedule_variance_days": variance, "next_gate": intel.get("next_gate"), "gate_date": intel.get("gate_date")}
    if eot is not None and variance is not None and variance < 0:
        summary = bi(
            f"{eot} days of extension requested while the project is already {abs(variance)} days behind; the next gate ({_text(intel.get('next_gate'))}, {intel.get('gate_date')}) is exposed.",
            f"对方申请工期延长 {eot} 天，而项目已落后 {abs(variance)} 天，下一关口（{(intel.get('next_gate') or {}).get('zh', '')}，{intel.get('gate_date')}）受影响。",
        )
    elif eot is not None:
        summary = bi(f"{eot} days of extension requested.", f"对方申请工期延长 {eot} 天。")
    else:
        summary = bi(f"No extension of time requested; response due {_text(ctx.case.deadline)}.", f"未申请工期延长；响应时限 {ctx.case.deadline.get('zh', '') if isinstance(ctx.case.deadline, dict) else ''}。")
    return ToolResult("schedule.impact", True, output, summary)


def cost_estimate(ctx: ToolContext, card: AgentCard) -> ToolResult:
    amounts = [{"currency": c.upper(), "amount": float(a.replace(",", ""))} for c, a in _AMOUNT_RE.findall(ctx.text)]
    quantities = [{"quantity": float(q), "unit": u.lower()} for q, u in _QUANTITY_RE.findall(ctx.text)]
    intel = PROJECT_INTELLIGENCE.get(ctx.project.id, {}) if ctx.project else {}
    headroom = round(intel["budget"] - intel["forecast"], 1) if intel.get("budget") is not None and intel.get("forecast") is not None else None
    output = {"claimed_amounts": amounts, "quantities": quantities, "budget_headroom_m": headroom}
    if not amounts and not quantities:
        output["status"] = "INSUFFICIENT_DATA"
        return ToolResult("cost.estimate", False, output, bi(
            "No amounts or quantities are stated, so the change cannot be valued yet.",
            "来函未写明金额或工程量，暂无法计价。",
        ))
    stated = ", ".join(f"{a['currency']} {a['amount']:,.0f}" for a in amounts) or ", ".join(f"{q['quantity']:g} {q['unit']}" for q in quantities)
    if headroom is None:
        budget_en, budget_zh = "project budget not available", "暂无项目预算数据"
    elif headroom < 0:
        budget_en, budget_zh = f"project forecast already {abs(headroom)} M over budget", f"项目预测已超预算 {abs(headroom)} 百万"
    else:
        budget_en, budget_zh = f"project budget headroom {headroom} M", f"项目预算余量 {headroom} 百万"
    return ToolResult("cost.estimate", True, output, bi(f"Stated: {stated}; {budget_en}.", f"来函写明：{stated}；{budget_zh}。"))


TOOLS = {
    "knowledge.search": knowledge_search,
    "case.precedents": case_precedents,
    "project.status": project_status,
    "twin.locate": twin_locate,
    "permit.gates": permit_gates,
    "schedule.impact": schedule_impact,
    "cost.estimate": cost_estimate,
}
