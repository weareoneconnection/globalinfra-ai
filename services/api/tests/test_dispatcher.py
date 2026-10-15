"""Dispatching assistant (``/assistant/dispatch``): multi-step plans, sub-agents,
streamed progress, summaries and conversation memory.

Mock mode exercises the deterministic planner; real-model tests monkeypatch
``app.dispatcher.generate`` so no network call is ever made.
"""
import json

import pytest

from app.dispatcher import (
    AGENT_IDS, DISPATCH_FORMAT, MAX_STEPS, PlanContext, dispatch_rules, parse_dispatch, validate_summary,
)

PROJECTS = {"MY-RAIL-A": 1, "ID-HWY-B": 2}
INCIDENT = "业主通知：P47 墩高处作业无防护，要求48小时内整改"


def _ctx(**kw):
    return PlanContext(project_codes=PROJECTS, known_case_ids=kw.pop("known", set()), **kw)


def _events(response):
    assert response.status_code == 200
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def _dispatch(client, message, **body):
    return _events(client.post("/assistant/dispatch?lang=zh", json={"message": message, **body}))


def _of(events, kind):
    return [e for e in events if e["type"] == kind]


# --- deterministic planner ----------------------------------------------------------

@pytest.mark.parametrize("message, agents", [
    ("马来西亚高处作业有什么要求？", ["knowledge"]),
    (INCIDENT, ["intake"]),
    ("待我审批", ["approvals"]),
    ("你好", []),
    ("查一下马来西亚高处作业规定，再看看项目进展", ["knowledge", "progress"]),
    ("项目进展，另外待我审批", ["progress", "approvals"]),
    ("我的上报处理得怎么样了", ["field"]),
])
def test_rules_dispatch(message, agents):
    assert [s.agent for s in dispatch_rules(message, _ctx())] == agents


def test_rules_put_one_intake_first_with_the_whole_message():
    message = "P47 墩发生坍塌事故有人受伤，查一下马来西亚事故报告规定"
    steps = dispatch_rules(message, _ctx())
    assert steps[0].agent == "intake" and steps[0].query == message
    assert sum(s.agent == "intake" for s in steps) == 1


def test_long_letters_are_never_split():
    letter = "Owner notice: " + "the contractor shall rectify the guardrail at Pier P47, then check the permit. " * 4
    assert [s.agent for s in dispatch_rules(letter, _ctx())] == ["intake"]


def test_this_case_resolves_to_the_conversation_case():
    steps = dispatch_rules("这个案例现在到哪一步了", _ctx(known={"CASE-ABC123"}, case_id="CASE-ABC123"))
    assert steps[0].agent == "case" and steps[0].case_id == "CASE-ABC123"


# --- model plan validation ---------------------------------------------------------

def _step(**fields):
    base = {"agent": "knowledge", "query": "", "case_id": "", "project_code": "", "question_id": 0, "answer": ""}
    base.update(fields)
    return base


def _plan(*steps, reply=""):
    return json.dumps({"steps": list(steps), "reply": reply})


def test_schema_enum_tracks_the_roster():
    items = DISPATCH_FORMAT["json_schema"]["schema"]["properties"]["steps"]["items"]
    assert items["properties"]["agent"]["enum"] == list(AGENT_IDS)


def test_parse_rejects_unverifiable_steps():
    ctx = _ctx(known={"CASE-ABC123"}, case_id="CASE-ABC123", open_questions={7: "Is the permit valid?"})
    assert parse_dispatch(_plan(_step(agent="approve_all")), ctx, "x") is None
    assert parse_dispatch(_plan(_step(agent="case", case_id="CASE-GHOST")), ctx, "x") is None
    assert parse_dispatch(_plan(_step(agent="case", case_id="NEW")), ctx, "x") is None  # no intake before it
    assert parse_dispatch(_plan(_step(agent="progress", project_code="XX")), ctx, "x") is None
    assert parse_dispatch(_plan(_step(agent="answer", question_id=99, answer="yes")), ctx, "x") is None
    assert parse_dispatch(_plan(_step(agent="answer", question_id=7, answer="")), ctx, "x") is None
    assert parse_dispatch(_plan(_step(agent="intake"), _step(agent="intake")), ctx, "x") is None
    assert parse_dispatch(_plan(), ctx, "x") is None  # no steps and no reply
    assert parse_dispatch("not json", ctx, "x") is None


def test_parse_accepts_a_chained_plan_and_caps_steps():
    ctx = _ctx(known={"CASE-ABC123"}, case_id="CASE-ABC123", open_questions={7: "Is the permit valid?"})
    steps, reply = parse_dispatch(_plan(
        _step(agent="intake", query=INCIDENT), _step(agent="case", case_id="new"),
        _step(agent="knowledge", query="Malaysia work at height"), _step(agent="answer", question_id=7, answer="Yes, PTW-0915"),
        _step(agent="approvals"),
    ), ctx, INCIDENT)
    assert [s.agent for s in steps] == ["intake", "case", "knowledge", "answer"] and len(steps) == MAX_STEPS
    assert steps[1].case_id == "NEW" and steps[3].case_id == "CASE-ABC123" and reply is None


def test_project_code_named_only_in_the_text_is_resolved():
    steps, _ = parse_dispatch(_plan(_step(agent="progress", query="MY-RAIL-A")), _ctx(), "MY-RAIL-A 进度怎么样")
    assert steps[0].project_id == 1


def test_summary_may_cite_only_steps_and_returned_sources():
    assert validate_summary("已建工单 [S1]，依据 [MY-HSE-WAH-01]。", 2, {"MY-HSE-WAH-01"})
    assert not validate_summary("已建工单。", 2, set())
    assert not validate_summary("见 [S3]。", 2, set())
    assert not validate_summary("已建工单 [S1]，依据 [OSHA-1910]。", 2, {"MY-HSE-WAH-01"})


# --- endpoint: offline -------------------------------------------------------------

def test_stream_runs_several_agents_and_summarises(client):
    events = _dispatch(client, "查一下马来西亚高处作业规定，再看看项目进展，另外待我审批")
    assert [e["type"] for e in events][:2] == ["session", "plan"] and events[-1]["type"] == "done"
    plan = _of(events, "plan")[0]
    assert plan["method"] == "rules" and [s["agent"] for s in plan["steps"]] == ["knowledge", "progress", "approvals"]
    assert plan["steps"][0]["name"] == "法规智能体"
    done = {e["index"]: e for e in _of(events, "step_done")}
    assert set(done) == {0, 1, 2} and all(e["status"] == "ok" for e in done.values())
    assert done[1]["data"]["projects"] and done[2]["data"]["count"] >= 0
    summary = _of(events, "summary")[0]
    assert summary["method"] == "rules" and "S1 法规智能体" in summary["text"]


def test_intake_step_creates_a_case_and_memory_resolves_this_case(client):
    events = _dispatch(client, INCIDENT)
    intake = _of(events, "step_done")[0]
    case_id = intake["data"]["case_id"]
    assert intake["status"] == "ok" and case_id.startswith("CASE-") and intake["data"]["team"]
    session_id = _of(events, "session")[0]["session_id"]

    follow = _dispatch(client, "这个案例现在到哪一步了", session_id=session_id)
    assert _of(follow, "session")[0]["context_case_id"] == case_id
    step = _of(follow, "step_done")[0]
    assert _of(follow, "plan")[0]["steps"][0]["agent"] == "case" and step["data"]["case_id"] == case_id
    turns = client.get(f"/assistant/sessions/{session_id}").json()["turns"]
    assert len(turns) == 4 and turns[0]["content"] == INCIDENT


def test_foreign_or_unknown_session_starts_fresh(client):
    events = _dispatch(client, "待我审批", session_id="not-a-session")
    assert _of(events, "session")[0]["session_id"] != "not-a-session"
    assert client.get("/assistant/sessions/not-a-session").status_code == 404


def test_greeting_gets_a_reply_without_steps(client):
    events = _dispatch(client, "你好")
    assert _of(events, "plan")[0]["steps"] == [] and _of(events, "reply")


# --- endpoint: with a (fake) model -----------------------------------------------------

def _real_mode(monkeypatch, responses):
    # Only the dispatcher sees a model; intake and analysis stay deterministic.
    monkeypatch.setattr("app.dispatcher._model_available", lambda payload: True)
    calls = []

    async def fake_generate(system, user, response_format=None, **_):
        calls.append(system)
        if response_format and response_format["json_schema"]["name"] == "assistant_dispatch":
            return responses["plan"]
        return responses.get("summary", "")
    monkeypatch.setattr("app.dispatcher.generate", fake_generate)
    return calls


def test_model_plan_chains_a_new_case_into_a_follow_up(client, monkeypatch):
    _real_mode(monkeypatch, {
        "plan": _plan(_step(agent="intake", query=INCIDENT), _step(agent="case", case_id="NEW")),
        "summary": "已建工单并完成分析 [S1]，当前状态见 [S2]。",
    })
    events = _dispatch(client, INCIDENT + "，建好后告诉我状态")
    done = {e["index"]: e for e in _of(events, "step_done")}
    assert done[0]["status"] == "ok" and done[1]["status"] == "ok"
    assert done[1]["data"]["case_id"] == done[0]["data"]["case_id"]
    assert _of(events, "plan")[0]["method"] == "llm"


def test_invalid_model_summary_falls_back_to_step_lines(client, monkeypatch):
    _real_mode(monkeypatch, {
        "plan": _plan(_step(agent="progress"), _step(agent="approvals")),
        "summary": "Everything is fine.",
    })
    summary = _of(_dispatch(client, "项目进展和待我审批"), "summary")[0]
    assert summary["method"] == "rules" and summary["text"].startswith("S1 ")


def test_model_cannot_skip_intake_for_a_reported_incident(client, monkeypatch):
    _real_mode(monkeypatch, {"plan": _plan(_step(agent="knowledge", query="work at height"))})
    plan = _of(_dispatch(client, INCIDENT), "plan")[0]
    assert [s["agent"] for s in plan["steps"]] == ["intake", "knowledge"]


def test_answer_agent_records_the_answer_and_reanalyses(client, monkeypatch):
    VO = ("Subcontractor letter, Malaysia: Request for Variation Order for additional anchor bolts at roof trusses T4 to T9 "
          "of Station S12, and an extension of time of 10 days. Please respond within 14 days.")
    first = _dispatch(client, VO)
    session_id = _of(first, "session")[0]["session_id"]
    case_id = _of(first, "step_done")[0]["data"]["case_id"]
    question = next(q for q in client.get(f"/cases/{case_id}/agent-run").json()["questions"] if q["status"] == "OPEN")
    _real_mode(monkeypatch, {"plan": _plan(_step(agent="answer", question_id=question["id"], answer="48 nos at RM 85"))})
    events = _dispatch(client, "48 nos at RM 85", session_id=session_id)
    step = _of(events, "step_done")[0]
    assert step["status"] == "ok" and step["data"]["reanalyzed"] is True
    after = client.get(f"/cases/{case_id}/agent-run").json()["questions"]
    assert next(q for q in after if q["id"] == question["id"])["status"] == "ANSWERED"
