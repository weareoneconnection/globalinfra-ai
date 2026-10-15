"""Coordinator, planner and verifier of the agent organization.

* The coordinator compares first-round findings, records conflicts and gaps,
  and sends at most one targeted follow-up to the agents concerned. Issues it
  cannot resolve are left for a human decision, never forced into a
  conclusion.
* The planner turns findings into steps that each trace back to a finding
  (or to the fixed governance steps) and carry an owner role and a due time.
* The verifier checks every finding and step before the case can reach
  human approval.
"""
from __future__ import annotations

import json
import re

from ..i18n import bi
from ..llm import LLMError, generate
from ..retrieval import tokenize
from .cards import CARDS
from .tools import CONFIDENT_RELEVANCE

# Disciplines whose findings must agree before a responsibility position is
# taken: a contractual position needs the technical facts behind it.
DEPENDENCIES = [
    ("contract", "engineering", bi("responsibility position depends on the technical cause", "责任立场取决于技术成因")),
    ("claims", "contract", bi("entitlement depends on the contractual basis", "权利主张取决于合同依据")),
    ("cost", "contract", bi("valuation depends on the change being instructed under the contract", "计价取决于变更是否已按合同指令")),
    ("compliance", "hse", bi("restart depends on both safety controls and permits", "复工同时取决于安全措施和许可")),
]


def detect_issues(findings: dict[str, dict]) -> list[dict]:
    """Deterministic conflict/gap detection over first-round findings."""
    issues = []
    for dependent, basis, reason in DEPENDENCIES:
        a, b = findings.get(dependent), findings.get(basis)
        if a and b and a["status"] == "SUPPORTED" and b["status"] != "SUPPORTED":
            issues.append({"type": "conflict", "agents": [dependent, basis], "follow_up": basis, "topic": reason,
                           "query": CARDS[basis].focus_terms})
    for agent_id, finding in findings.items():
        if finding["status"] != "SUPPORTED" and not any(agent_id == i["follow_up"] for i in issues):
            issues.append({"type": "gap", "agents": [agent_id], "follow_up": agent_id,
                           "topic": bi(f"no confident evidence for {CARDS[agent_id].focus['en']}", f"{CARDS[agent_id].focus['zh']}缺少可靠依据"),
                           "query": " ".join(g["en"] for g in finding.get("gaps", []))})
    return issues


COORDINATION_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "coordination", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["issues"],
        "properties": {"issues": {"type": "array", "maxItems": 3, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["agents", "follow_up", "topic_en", "topic_zh", "question"],
            "properties": {"agents": {"type": "array", "items": {"type": "string"}}, "follow_up": {"type": "string"},
                           "topic_en": {"type": "string"}, "topic_zh": {"type": "string"}, "question": {"type": "string"}},
        }}},
    }},
}


async def model_issues(findings: dict[str, dict], budget, route, sensitivity) -> list[dict]:
    """Let the model spot contradictions the dependency table cannot express."""
    if len(findings) < 2 or not budget.take():
        return []
    listing = "\n".join(f"- {aid} ({f['status']}): {f['claim']['en']}" for aid, f in findings.items())
    system = ("You coordinate specialist agents. List at most two GENUINE CONTRADICTIONS: cases where two agents' "
              "conclusions disagree with each other. Missing facts, open questions or evidence still to be provided are NOT "
              "contradictions; never list them. For each contradiction, name the agents involved, which single agent should "
              "follow up, the topic in English and Chinese, and the follow-up question. Return an empty list when the "
              "conclusions are consistent, which is the normal case.")
    try:
        raw = await generate(system, listing, response_format=COORDINATION_FORMAT, route=route, sensitivity=sensitivity)
        data = json.loads(re.search(r"\{.*\}", raw or "", re.DOTALL).group(0))
    except (LLMError, ValueError, AttributeError):
        return []
    issues = []
    for item in data.get("issues", [])[:2]:
        agents = [a for a in item.get("agents", []) if a in findings]
        follow_up = item.get("follow_up")
        if len(agents) >= 1 and follow_up in findings and str(item.get("topic_en") or "").strip():
            issues.append({"type": "conflict", "agents": agents, "follow_up": follow_up,
                           "topic": bi(item["topic_en"][:200], (item.get("topic_zh") or item["topic_en"])[:200]),
                           "query": str(item.get("question") or "")[:300], "method": "llm"})
    return issues


def _due(case_deadline: dict, urgent: bool) -> dict:
    if urgent:
        return bi("immediately", "立即")
    en = (case_deadline or {}).get("en") or "as agreed"
    zh = (case_deadline or {}).get("zh") or "按约定"
    return bi(f"within {en}" if en[0].isdigit() else en, f"{zh}内" if zh[0].isdigit() else zh)


MAX_ACTION_STEPS = 6
MAX_QUESTION_STEPS = 3
ACTION_SIMILARITY = 0.35


def _tokens(text: str) -> set[str]:
    return set(tokenize(text))


def raw_actions(team: list[str], findings: dict[str, dict]) -> list[dict]:
    return [
        {"agent_id": agent_id, "text": action["text"], "owner_role": action["owner_role"],
         "refs": list(findings[agent_id].get("evidence_refs", []))}
        for agent_id in team for action in findings[agent_id].get("actions", [])
    ]


CONSOLIDATION_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "consolidation", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["actions", "questions"],
        "properties": {
            "actions": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                        "required": ["ids", "text_en", "text_zh"],
                        "properties": {"ids": {"type": "array", "items": {"type": "integer"}},
                                       "text_en": {"type": "string"}, "text_zh": {"type": "string"}}}},
            "questions": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                          "required": ["ids", "text_en", "text_zh"],
                          "properties": {"ids": {"type": "array", "items": {"type": "integer"}},
                                         "text_en": {"type": "string"}, "text_zh": {"type": "string"}}}},
        },
    }},
}


def _groups(items: list, ids_expected: int) -> list[dict] | None:
    seen: list[int] = []
    groups = []
    for item in items or []:
        ids = [i for i in item.get("ids", []) if isinstance(i, int)]
        if not ids or not str(item.get("text_en") or "").strip():
            return None
        seen += ids
        groups.append({"ids": ids, "text": bi(item["text_en"].strip()[:300], (item.get("text_zh") or item["text_en"]).strip()[:300])})
    # every original item exactly once, nothing invented
    return groups if sorted(seen) == list(range(ids_expected)) else None


async def consolidate(actions: list[dict], questions: list[dict], budget, route, sensitivity) -> tuple[list[dict] | None, list[dict] | None]:
    """Merge semantically equivalent actions and questions with the model.

    Returns (merged_actions, merged_questions) in the planner's shapes, or
    (None, None) when the model is unavailable or its grouping is invalid.
    """
    if len(actions) + len(questions) < 2 or not budget.take():
        return None, None
    listing = {
        "actions": [{"id": i, "text": a["text"]["en"]} for i, a in enumerate(actions)],
        "questions": [{"id": i, "text": q["question"]["en"]} for i, q in enumerate(questions)],
    }
    system = ("Merge items that ask for or do the same thing. Put EVERY id in exactly one group. Write each group's text "
              "as one concise sentence in English and Simplified Chinese using only information from its items; add "
              "nothing new. Keep distinct items in separate groups.")
    try:
        raw = await generate(system, json.dumps(listing, ensure_ascii=False), response_format=CONSOLIDATION_FORMAT,
                             route=route, sensitivity=sensitivity)
        data = json.loads(re.search(r"\{.*\}", raw or "", re.DOTALL).group(0))
    except (LLMError, ValueError, AttributeError):
        return None, None
    action_groups, question_groups = _groups(data.get("actions"), len(actions)), _groups(data.get("questions"), len(questions))
    if action_groups is None or question_groups is None:
        return None, None
    merged_actions = []
    for group in action_groups:
        members = [actions[i] for i in group["ids"]]
        owners = list({m["owner_role"]["en"]: m["owner_role"] for m in members}.values())
        merged_actions.append({"text": group["text"], "owners": owners, "agents": [m["agent_id"] for m in members],
                               "refs": list(dict.fromkeys(r for m in members for r in m["refs"]))})
    merged_questions = []
    for group in question_groups:
        members = [questions[i] for i in group["ids"]]
        merged_questions.append({**members[0], "question": group["text"], "also_from": [m["agent_id"] for m in members[1:]]})
    return merged_actions, merged_questions


def merge_actions(actions: list[dict]) -> list[dict]:
    """Lexical fallback: one step per distinct action; owners of similar actions are combined."""
    merged: list[dict] = []
    for action in actions:
        tokens = _tokens(action["text"]["en"])
        target = next((m for m in merged if tokens and m["tokens"] and
                       len(tokens & m["tokens"]) / len(tokens | m["tokens"]) >= ACTION_SIMILARITY), None)
        if target is None:
            merged.append({"text": action["text"], "owners": [action["owner_role"]], "agents": [action["agent_id"]],
                           "refs": list(action["refs"]), "tokens": tokens})
        else:
            if action["owner_role"]["en"] not in [o["en"] for o in target["owners"]]:
                target["owners"].append(action["owner_role"])
            target["agents"].append(action["agent_id"])
            target["refs"] = list(dict.fromkeys(target["refs"] + action["refs"]))
    return merged


def build_plan(team: list[str], findings: dict[str, dict], open_questions: list[dict], case_deadline: dict,
               risk: str, unresolved: list[dict], merged_actions: list[dict] | None = None) -> list[dict]:
    """Every step traces to a finding, an open question, an unresolved issue or a governance gate."""
    steps: list[dict] = []

    def add(text: dict, owner: dict, due: dict, source: str, refs=(), depends=()):
        step_id = f"S{len(steps) + 1}"
        steps.append({"id": step_id, "text": text, "owner_role": owner, "due": due, "source": source,
                      "evidence_refs": list(refs), "depends_on": list(depends)})
        return step_id

    urgent = risk == "CRITICAL"
    action_ids = []
    for action in (merged_actions if merged_actions is not None else merge_actions(raw_actions(team, findings)))[:MAX_ACTION_STEPS]:
        owner = bi(" / ".join(o["en"] for o in action["owners"]), "、".join(o["zh"] for o in action["owners"]))
        action_ids.append(add(action["text"], owner, _due(case_deadline, urgent),
                              "finding:" + "+".join(dict.fromkeys(action["agents"])), action["refs"]))
    for question in open_questions[:MAX_QUESTION_STEPS]:
        card = CARDS[question["agent_id"]]
        action_ids.append(add(bi(f"Obtain from the project team: {question['question']['en']}", f"向项目团队补充：{question['question']['zh']}"),
                              bi("Project Manager", "项目经理"), _due(case_deadline, False), f"question:{question['agent_id']}"))
    for issue in unresolved:
        action_ids.append(add(bi(f"Decide: {issue['topic']['en']}", f"人工决定：{issue['topic']['zh']}"),
                              bi("Project Manager", "项目经理"), _due(case_deadline, False), f"issue:{'+'.join(issue['agents'])}"))
    pack = add(bi("Assemble the evidence pack", "汇总完整证据包"), bi("Document Controller", "文控负责人"),
               _due(case_deadline, False), "governance", depends=action_ids)
    draft = add(bi("Draft the governed reply", "起草受管控的回复"), bi("Contract Manager", "合同经理"),
                _due(case_deadline, False), "governance", depends=[pack])
    approvers = bi("Project Manager", "项目经理") if not (urgent and "hse" in team) else bi("Project Manager and HSE Manager", "项目经理与 HSE 经理")
    add(bi("Obtain human approval before any external action", "对外行动前取得人工审批"), approvers,
        _due(case_deadline, urgent), "governance", depends=[draft])
    return steps


def verify(team: list[str], findings: dict[str, dict], plan: list[dict], unresolved: list[dict]) -> dict:
    checks = []
    for agent_id in team:
        f = findings[agent_id]
        ok = f["status"] != "SUPPORTED" or (bool(f["evidence_refs"]) and set(f["evidence_refs"]) <= set(f["retrieved_refs"]))
        checks.append({"check": f"finding:{agent_id}", "passed": ok,
                       "detail": bi("claim is backed by retrieved evidence" if ok else "claim not backed by retrieved evidence",
                                    "结论有检索证据支撑" if ok else "结论缺少检索证据支撑")})
    traceable = all(step["source"] for step in plan)
    checks.append({"check": "plan:traceable", "passed": traceable,
                   "detail": bi("every plan step traces to a finding, question or governance gate", "每个计划步骤都可追溯到结论、问题或治理关卡")})
    checks.append({"check": "issues:escalated", "passed": True,
                   "detail": bi(f"{len(unresolved)} unresolved issue(s) left for a human decision", f"{len(unresolved)} 个未解决问题已交由人工决定")})
    total = len(team)
    supported = [a for a in team if findings[a]["status"] == "SUPPORTED"]
    cited = [a for a in team if findings[a]["retrieved_refs"]]
    return {
        "checks": checks, "passed": all(c["passed"] for c in checks),
        "citation_score": round(len(cited) / total, 3) if total else 0.0,
        "consistency_score": round(len(supported) / total, 3) if total else 0.0,
        "supported": supported, "confident_threshold": CONFIDENT_RELEVANCE,
    }
