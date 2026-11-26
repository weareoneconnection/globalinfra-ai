"""Dispatcher P1 (new sub-agents, depends_on) and P2 (retry, sentence check,
clarification, country focus, trace). Rules mode; model calls are patched."""
import json

import pytest

from app import dispatcher
from app.dispatcher import MAX_STEPS, PlanContext, Step, _dedupe, dispatch_rules, filter_sentences, parse_dispatch

LETTER = ("尊敬的承包商：贵方在印尼雅加达项目施工中占用了我方便道，造成居民通行受阻，请于7日内书面答复并恢复原状。"
          "请建工单、查相关条款并起草回函要点。")


def _dispatch(client, message, **body):
    response = client.post("/assistant/dispatch?lang=zh", json={"message": message, **body})
    assert response.status_code == 200
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def _plan(events):
    return next(e for e in events if e["type"] == "plan")["steps"]


def _done(events, agent):
    index = next(s["index"] for s in _plan(events) if s["agent"] == agent)
    return next(e for e in events if e["type"] == "step_done" and e["index"] == index)


def _ctx(**kw):
    return PlanContext(project_codes={"MY-RAIL-A": 1}, known_case_ids=set(), **kw)


# --- planning -------------------------------------------------------------------

@pytest.mark.parametrize("message, agents", [
    ("比较马来西亚和沙特对工伤的规定", ["compare"]),
    ("服务期满酬金用阿语怎么说？阿联酋", ["glossary"]),
    ("沙特项目施工阶段需要哪些许可？", ["gates"]),
    ("图纸上桥墩的尺寸是多少？", ["drawing"]),
    (LETTER, ["intake", "knowledge", "draft"]),
])
def test_rules_route_the_new_agents(message, agents):
    assert [s.agent for s in dispatch_rules(message, _ctx())] == agents


def test_letter_draft_depends_on_everything_before_it():
    steps = dispatch_rules(LETTER, _ctx())
    assert steps[-1].depends_on == [0, 1] and len(steps) <= MAX_STEPS


def test_dedupe_keeps_dependencies_pointing_at_kept_steps():
    steps = _dedupe([Step("knowledge", query="a"), Step("knowledge", query="a"), Step("glossary", query="b"),
                     Step("draft", depends_on=[1, 2])])
    assert [s.agent for s in steps] == ["knowledge", "glossary", "draft"]
    assert steps[-1].depends_on == [0, 1]


def test_model_plan_dependencies_are_validated():
    ok = json.dumps({"steps": [{"agent": "knowledge", "query": "q", "depends_on": []},
                               {"agent": "draft", "query": "", "depends_on": [0]}], "reply": ""})
    steps, _ = parse_dispatch(ok, _ctx(), "m")
    assert steps[1].depends_on == [0]
    forward = json.dumps({"steps": [{"agent": "knowledge", "query": "q", "depends_on": [1]},
                                    {"agent": "glossary", "query": "t", "depends_on": []}], "reply": ""})
    assert parse_dispatch(forward, _ctx(), "m") is None
    first_draft = json.dumps({"steps": [{"agent": "draft", "query": "", "depends_on": []}], "reply": ""})
    assert parse_dispatch(first_draft, _ctx(), "m") is None


# --- sentence-level citation check ---------------------------------------------

def test_filter_sentences_drops_unsupported_sentences():
    text = "沙特斋月每天最多 6 小时 [S1]。马来西亚也一样。阿联酋另有规定 [AE-FAKE]。请确认是否需要回函 [S2] [SA-LABOR-ART-98]。"
    kept, dropped = filter_sentences(text, 2, {"SA-LABOR-ART-98"})
    assert dropped == 2
    assert "马来西亚" not in kept and "AE-FAKE" not in kept
    assert "[S1]" in kept and "[S2]" in kept


def test_filter_sentences_keeps_trailing_citation_with_its_sentence():
    kept, dropped = filter_sentences("Ramadan hours are capped. [S1] Overtime is paid at 150%. [S3]", 2, set())
    assert kept == "Ramadan hours are capped. [S1]" and dropped == 1


async def _fake_generate(*args, **kwargs):
    return "已建工单 [S1]。条款见 [S2]。另外业主一定会索赔。"


def test_summary_cuts_the_uncited_sentence(client, monkeypatch):
    monkeypatch.setattr(dispatcher, "_model_available", lambda payload: True)

    async def plan_rules_only(payload, lang, ctx, history):
        return dispatcher.dispatch_rules(payload.message, ctx), None, "rules"

    monkeypatch.setattr(dispatcher, "plan_dispatch", plan_rules_only)
    monkeypatch.setattr(dispatcher, "generate", _fake_generate)
    import app.dispatch_agents as agents
    monkeypatch.setattr(agents, "_model_available", lambda payload: False)
    monkeypatch.setattr(dispatcher, "_grounded_answer", lambda *a, **k: _none())
    events = _dispatch(client, "沙特斋月工时有什么规定？另外比较马来西亚和沙特的工伤报告要求")
    summary = next(e for e in events if e["type"] == "summary")
    assert summary["method"] == "llm" and summary["dropped_sentences"] == 1
    assert "索赔" not in summary["text"]


async def _none():
    return None


# --- the new sub-agents --------------------------------------------------------

def test_compare_builds_one_row_per_country(client):
    data = _done(_dispatch(client, "比较马来西亚和沙特对工伤的规定"), "compare")["data"]
    assert [r["country"] for r in data["table"]] == ["MY", "SA"]
    for row in data["table"]:
        assert row["clauses"] and all(c["country_code"] == row["country"] for c in row["clauses"])


def test_glossary_marks_official_terms(client):
    terms = _done(_dispatch(client, "服务期满酬金用阿语怎么说？阿联酋"), "glossary")["data"]["terms"]
    assert terms[0]["country"] == "AE" and terms[0]["local"] == "مكافأة نهاية الخدمة"
    assert terms[0]["attested"] is True


def test_gates_lists_the_stage_permits(client):
    step = _done(_dispatch(client, "沙特项目施工阶段需要哪些许可？"), "gates")
    assert step["data"]["stage"] == "construction" and step["data"]["countries"] == ["SA"]
    assert step["data"]["gates"][0]["gates"]
    assert "施工阶段" in step["summary"]


def test_drawing_without_a_reference_asks_which(client):
    data = _done(_dispatch(client, "图纸上桥墩的尺寸是多少？"), "drawing")["data"]
    assert "drawing_id" not in data  # never guesses a drawing


def test_letter_draft_is_never_sent_and_cites_only_retrieved_clauses(client):
    events = _dispatch(client, LETTER)
    intake, knowledge, draft = (_done(events, a) for a in ("intake", "knowledge", "draft"))
    assert draft["status"] == "ok" and draft["data"]["status"] == "DRAFT_NOT_SENT"
    assert draft["case_id"] == intake["case_id"]
    assert set(draft["refs"]) <= set(knowledge["refs"])
    assert all(set(p["refs"]) <= set(knowledge["refs"]) for p in draft["data"]["points"])
    assert "未发送" in draft["summary"]
    starts = [e["index"] for e in events if e["type"] == "step_start"]
    assert starts.index(2) > starts.index(0)  # waited for its inputs


# --- clarification, focus and trace --------------------------------------------

def test_no_country_and_divergent_hits_asks_which_country(client):
    events = _dispatch(client, "工人斋月期间每天最多工作几小时？加班怎么算？")
    clarify = [e for e in events if e["type"] == "clarify"]
    data = _done(events, "knowledge")["data"]
    if len({h["country_code"] for h in data["hits"]}) > 1:
        assert clarify and len(clarify[0]["options"]) > 1
    else:
        assert not clarify


def test_follow_up_keeps_the_country_focus(client):
    first = _dispatch(client, "沙特斋月期间每天最多工作几小时？")
    session_id = next(e for e in first if e["type"] == "session")["session_id"]
    follow = _dispatch(client, "那加班费呢？", session_id=session_id)
    data = _done(follow, "knowledge")["data"]
    assert data["countries"] == ["SA"]
    assert {h["country_code"] for h in data["hits"]} <= {"SA", None}
    switch = _dispatch(client, "那马来西亚的加班费呢？", session_id=session_id)
    assert _done(switch, "knowledge")["data"]["countries"] == ["MY"]


def test_trace_is_streamed_and_stored(client):
    events = _dispatch(client, "沙特斋月期间每天最多工作几小时？另外沙特项目施工阶段需要哪些许可？")
    trace = next(e for e in events if e["type"] == "trace")
    assert [s["agent"] for s in trace["steps"]] == ["knowledge", "gates"]
    assert all(s["duration_ms"] >= 0 for s in trace["steps"]) and "SA-LABOR-ART-98" in trace["refs"]
    assert [e["type"] for e in events][-2:] == ["trace", "done"]
    session_id = next(e for e in events if e["type"] == "session")["session_id"]
    stored = client.get(f"/assistant/sessions/{session_id}/trace").json()["trace"]
    assert stored["steps"] == trace["steps"]


def test_bounded_retry_rewrites_once(client, monkeypatch):
    calls = []

    async def rewrite(system, prompt, **kwargs):
        calls.append(system)
        return "Ramadan working hours"

    monkeypatch.setattr(dispatcher, "_model_available", lambda payload: True)

    async def plan_rules_only(payload, lang, ctx, history):
        return dispatcher.dispatch_rules(payload.message, ctx), None, "rules"

    monkeypatch.setattr(dispatcher, "plan_dispatch", plan_rules_only)
    monkeypatch.setattr(dispatcher, "generate", rewrite)
    monkeypatch.setattr(dispatcher, "_grounded_answer", lambda *a, **k: _none())
    data = _done(_dispatch(client, "沙特 xyzzy 规定是什么？"), "knowledge")["data"]
    assert data["retried"] is True and len([c for c in calls if c == dispatcher.REWRITE_SYSTEM]) == 1
    assert "SA-LABOR-ART-98" in [h["source_ref"] for h in data["hits"]]
