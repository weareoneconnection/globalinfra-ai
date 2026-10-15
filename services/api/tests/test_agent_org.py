"""Agent organization 2.0: cards, team assembly, tools, questions and the
organization endpoints. Deterministic (no model configured)."""
from app.agent_org.cards import CARDS, GOVERNANCE_AGENTS, SPECIALIST_IDS
from app.agent_org.team import rule_team
from app.workflow import DEFAULT_SPECIALISTS, SPECIALISTS_BY_CASE_TYPE

VO = ("Subcontractor letter, Malaysia: Request for Variation Order for additional anchor bolts at roof trusses T4 to T9 "
      "of Station S12, and an extension of time of 10 days. Please register this variation request and respond within 14 days.")


def _intake(client, text, project_id=1):
    return client.post("/intake/text", json={"text": text, "project_id": project_id}).json()["case_id"]


def _run(client, case_id):
    return client.get(f"/cases/{case_id}/agent-run").json()


# --- cards -------------------------------------------------------------------

def test_every_routed_specialist_has_an_advisory_card():
    for team in SPECIALISTS_BY_CASE_TYPE.values():
        for agent_id in team:
            assert agent_id in CARDS
    assert all(CARDS[a].authority == "advise_only" for a in CARDS)
    assert not set(GOVERNANCE_AGENTS) & set(SPECIALIST_IDS)


def test_cards_endpoint_exposes_tools_policy_and_country_variants(client):
    cards = {c["id"]: c for c in client.get("/agents/cards?lang=en").json()}
    assert "schedule.impact" in cards["claims"]["tools"]
    assert cards["hse"]["countries"] and "MY" in cards["hse"]["countries"]
    assert cards["verification"]["governance"] is True


# --- team assembly -------------------------------------------------------------

def test_team_starts_from_core_and_adds_members_with_reasons():
    team = rule_team(VO, "Contract / Technical Interface", "MEDIUM", SPECIALISTS_BY_CASE_TYPE, DEFAULT_SPECIALISTS,
                     label={"en": "Contract / Technical Interface", "zh": "合同 / 技术接口"})
    ids = [m.agent_id for m in team]
    assert ids[:3] == SPECIALISTS_BY_CASE_TYPE["Contract / Technical Interface"]
    assert {"cost", "claims"} <= set(ids) and "hse" not in ids
    added = [m for m in team if m.source == "signal"]
    assert all("signal" in m.rationale["en"] and "触发词" in m.rationale["zh"] for m in added)


def test_team_size_is_capped():
    text = VO + " supplier delivery crane commissioning handover work package claim"
    assert len(rule_team(text, "Contract / Technical Interface", "CRITICAL", SPECIALISTS_BY_CASE_TYPE, DEFAULT_SPECIALISTS)) <= 6


# --- tools and quantification ------------------------------------------------------

def test_schedule_and_cost_tools_read_the_full_letter(client):
    run = _run(client, _intake(client, VO))
    claims = next(f for f in run["findings"] if f["agent_id"] == "claims")
    schedule = next(t for t in claims["tool_calls"] if t["tool"] == "schedule.impact")
    assert schedule["output"]["eot_requested_days"] == 10
    assert schedule["output"]["project_schedule_variance_days"] == -18
    cost = next(f for f in run["findings"] if f["agent_id"] == "cost")
    estimate = next(t for t in cost["tool_calls"] if t["tool"] == "cost.estimate")
    assert estimate["output"]["status"] == "INSUFFICIENT_DATA" and cost["status"] == "NEEDS_INPUT"


def test_twin_and_permit_tools_resolve_project_data(client):
    run = _run(client, _intake(client, "Owner notice, Malaysia: workers at height near an unprotected edge at Pier P47 without fall protection."))
    hse = next(f for f in run["findings"] if f["agent_id"] == "hse")
    tools = {t["tool"]: t for t in hse["tool_calls"]}
    assert any(o["twin_id"].endswith("-P47") for o in tools["twin.locate"]["output"]["objects"])
    assert tools["permit.gates"]["output"]["country"] == "MY" and tools["permit.gates"]["output"]["gates"]


def test_precedents_come_from_resolved_cases_of_the_same_type(client):
    first = _intake(client, VO)
    for approval in client.get("/approvals").json():
        if approval["case_id"] == first:
            client.post(f"/approvals/{approval['id']}/approve")
    action_id = client.get(f"/cases/{first}").json()["action"]["id"]
    for step in ("execute", "verify", "close"):
        assert client.post(f"/actions/{action_id}/{step}").status_code == 200
    run = _run(client, _intake(client, VO))
    contract = next(f for f in run["findings"] if f["agent_id"] == "contract")
    precedents = next(t for t in contract["tool_calls"] if t["tool"] == "case.precedents")["output"]["precedents"]
    assert first in [p["case_id"] for p in precedents]


# --- questions, plan, verification ---------------------------------------------------

def test_agent_question_answer_triggers_reanalysis(client):
    case_id = _intake(client, VO)
    run = _run(client, case_id)
    question = next(q for q in run["questions"] if q["agent_id"] == "cost")
    r = client.post(f"/cases/{case_id}/inputs", json={"input_id": question["id"], "answer": "48 nos at RM 85, total RM 4,080."})
    assert r.status_code == 200 and r.json()["reanalyzed"] is True
    after = _run(client, case_id)
    cost = next(f for f in after["findings"] if f["agent_id"] == "cost")
    assert cost["status"] == "SUPPORTED"
    assert next(q for q in after["questions"] if q["id"] == question["id"])["status"] == "ANSWERED"


def test_plan_steps_trace_to_findings_and_governance(client):
    run = _run(client, _intake(client, VO))
    assert run["plan"] and all(step["source"] for step in run["plan"])
    assert run["plan"][-1]["source"] == "governance"
    assert run["verification"]["passed"] is True


def test_inputs_endpoint_rejects_foreign_question(client):
    a, b = _intake(client, VO), _intake(client, VO)
    question = _run(client, a)["questions"][0]
    assert client.post(f"/cases/{b}/inputs", json={"input_id": question["id"], "answer": "x"}).status_code == 404


def test_runs_and_scorecards_reflect_latest_runs(client):
    case_id = _intake(client, VO)
    client.post(f"/cases/{case_id}/analyze")
    runs = client.get("/agents/runs?limit=50").json()
    assert [r for r in runs if r["case_id"] == case_id]
    scores = {s["agent_id"]: s for s in client.get("/agents/scorecards").json()}
    assert scores["cost"]["runs"] >= 1 and scores["cost"]["needs_input_rate"] is not None


def test_similar_questions_from_several_agents_are_asked_once():
    from app.agent_org.orchestrator import merge_questions
    q = lambda agent, en: {"agent_id": agent, "question": {"en": en, "zh": en}, "key": agent}  # noqa: E731
    merged = merge_questions([
        q("engineering", "Which written instruction or drawing revision required the additional anchor bolts?"),
        q("claims", "Which written instruction or drawing revision required the additional anchor bolts at T4 to T9?"),
        q("cost", "Please provide the quantities and the rate build-up for the claimed change."),
    ])
    assert [m["agent_id"] for m in merged] == ["engineering", "cost"]
    assert merged[0]["also_from"] == ["claims"]


def test_similar_actions_from_several_agents_become_one_plan_step():
    from app.agent_org.coordination import build_plan
    from app.i18n import bi

    def finding(text, owner):
        return {"status": "SUPPORTED", "evidence_refs": ["PROC-VO-02"], "retrieved_refs": ["PROC-VO-02"],
                "actions": [{"text": bi(text, text), "owner_role": bi(owner, owner)}]}

    findings = {
        "contract": finding("Register the letter as a variation request and acknowledge receipt", "Contract Manager"),
        "cost": finding("Register the variation request and acknowledge receipt without admitting cost", "Quantity Surveyor"),
        "claims": finding("Review the extension of time against the critical path", "Planning Engineer"),
    }
    plan = build_plan(list(findings), findings, [], bi("14 days", "14 天"), "MEDIUM", [])
    actions = [s for s in plan if s["source"].startswith("finding:")]
    assert len(actions) == 2
    assert actions[0]["owner_role"]["en"] == "Contract Manager / Quantity Surveyor"
    assert actions[0]["source"] == "finding:contract+cost"
