"""Dynamic team assembly.

The team starts from the core specialists for the case type (the same
mapping intake uses for ``recommended_agents``), then adds specialists
whose trigger signals appear in the case. When a model is configured it may
propose up to two further specialists from the card registry; proposals
outside the registry, governance agents and duplicates are ignored. Every
member carries the reason it was selected.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..i18n import bi
from ..llm import LLMError, generate
from .cards import CARDS, SPECIALIST_IDS

MAX_TEAM = 6
MAX_MODEL_ADDITIONS = 2

# (agent, trigger keywords, bilingual reason). Keywords are matched on the
# lowercased case text; first-listed triggers are the strongest.
TRIGGERS: list[tuple[str, tuple[str, ...], dict]] = [
    ("cost", ("variation", "valuation", "bill of quantities", "cost", "price", "rate build", "变更", "计价", "费用", "签证"),
     bi("the case involves a change that must be valued", "案例涉及需要计价的变更")),
    ("claims", ("extension of time", "eot", "claim", "entitlement", "delay", "variation order", "索赔", "工期延长", "延误", "权利"),
     bi("the case raises entitlement or extension-of-time questions", "案例涉及权利主张或工期延长")),
    ("procurement", ("supplier", "procurement", "purchase order", "delivery", "lead time", "供应商", "采购", "交付"),
     bi("the case depends on supply or delivery", "案例涉及供应或交付")),
    ("plant", ("crane", "lifting", "heavy lift", "plant", "equipment", "吊装", "起重机", "设备"),
     bi("the case involves lifting or plant", "案例涉及吊装或机械设备")),
    ("workforce", ("registration", "competency", "competent person", "training", "toolbox", "注册", "资质", "培训", "交底"),
     bi("the case involves personnel competency or registration", "案例涉及人员资质或注册")),
    ("commissioning", ("commissioning", "punch list", "system readiness", "调试", "遗留项"),
     bi("the case affects commissioning readiness", "案例影响调试就绪")),
    ("asset", ("handover", "asset register", "maintenance plan", "移交", "资产台账", "维护计划"),
     bi("the case affects asset handover or maintenance", "案例影响资产移交或维护")),
    ("construction", ("work package", "crew", "sequence", "工作包", "班组", "施工顺序"),
     bi("the case changes site execution", "案例影响现场施工安排")),
]


@dataclass(frozen=True)
class Member:
    agent_id: str
    source: str  # core | signal | model
    rationale: dict

    def payload(self) -> dict:
        card = CARDS[self.agent_id]
        return {"agent_id": self.agent_id, "name": card.name, "source": self.source, "rationale": self.rationale}


def _core(case_type: str, label: dict, core_map: dict, default: list) -> list[Member]:
    return [
        Member(agent_id, "core", bi(f"core specialist for {label.get('en') or case_type} cases", f"{label.get('zh') or case_type}类案例的核心专业成员"))
        for agent_id in core_map.get(case_type, default)
    ]


def rule_team(text: str, case_type: str, risk: str, core_map: dict, default: list, label: dict | None = None) -> list[Member]:
    lowered = text.lower()
    team = _core(case_type, label or {}, core_map, default)
    chosen = {member.agent_id for member in team}
    for agent_id, keywords, reason in TRIGGERS:
        if len(team) >= MAX_TEAM:
            break
        hit = next((k for k in keywords if k in lowered), None)
        if hit and agent_id not in chosen:
            team.append(Member(agent_id, "signal", bi(f"{reason['en']} (signal: “{hit}”)", f"{reason['zh']}（触发词：“{hit}”）")))
            chosen.add(agent_id)
    if risk == "CRITICAL" and "risk" not in chosen and len(team) < MAX_TEAM:
        team.append(Member("risk", "signal", bi("critical risk level requires a risk owner", "紧急风险等级需要指定风险负责人")))
    return team


TEAM_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "team_additions", "strict": True,
        "schema": {
            "type": "object", "additionalProperties": False, "required": ["additions"],
            "properties": {"additions": {"type": "array", "maxItems": MAX_MODEL_ADDITIONS, "items": {
                "type": "object", "additionalProperties": False, "required": ["agent_id", "reason_en", "reason_zh"],
                "properties": {"agent_id": {"type": "string", "enum": list(SPECIALIST_IDS)},
                               "reason_en": {"type": "string"}, "reason_zh": {"type": "string"}},
            }}},
        },
    },
}


def _parse_additions(raw: str, chosen: set[str]) -> list[Member]:
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return []
    members = []
    for item in (data.get("additions") or [])[:MAX_MODEL_ADDITIONS]:
        agent_id = str(item.get("agent_id") or "")
        reason_en, reason_zh = str(item.get("reason_en") or "").strip(), str(item.get("reason_zh") or "").strip()
        if agent_id in SPECIALIST_IDS and agent_id not in chosen and reason_en:
            members.append(Member(agent_id, "model", bi(reason_en[:200], (reason_zh or reason_en)[:200])))
            chosen.add(agent_id)
    return members


async def model_additions(text: str, team: list[Member], budget, route, sensitivity) -> list[Member]:
    """Ask the model whether a missing specialist is needed. Never removes members."""
    if len(team) >= MAX_TEAM or not budget.take():
        return []
    roster = "\n".join(f"- {cid}: {CARDS[cid].focus['en']}" for cid in SPECIALIST_IDS)
    current = ", ".join(member.agent_id for member in team)
    system = (
        "You staff a specialist team for an overseas infrastructure project case. Propose at most two additional "
        "specialists from the roster ONLY if the case clearly needs their discipline and nobody in the current team "
        "covers it. Propose none when the team is sufficient. Give a one-sentence reason in English and Chinese."
    )
    user = f"Roster:\n{roster}\n\nCurrent team: {current}\n\nCase:\n{text[:3000]}"
    try:
        raw = await generate(system, user, response_format=TEAM_FORMAT, route=route, sensitivity=sensitivity)
    except LLMError:
        return []
    return _parse_additions(raw, {member.agent_id for member in team})[: MAX_TEAM - len(team)]
