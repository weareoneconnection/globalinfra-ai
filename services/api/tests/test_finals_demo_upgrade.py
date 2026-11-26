"""Finals Mission Control must show a real completed judge run when one exists."""


def _h(ticket: str) -> dict[str, str]:
    return {"X-Competition-Role-Ticket": ticket}


def _run_full_session(client) -> str:
    created = client.post("/competition/sessions")
    assert created.status_code == 201, created.text
    sid = created.json()["session"]["id"]
    tickets = {k: v["ticket"] for k, v in created.json()["role_tickets"].items()}
    state = client.post(f"/competition/sessions/{sid}/analyze", headers=_h(tickets["project_manager"])).json()
    approvals = {row["required_role"]: row["id"] for row in state["approvals"]}
    for role in ("project_manager", "hse_manager"):
        r = client.post(f"/competition/sessions/{sid}/approvals/{approvals[role]}/approve", headers=_h(tickets[role]))
        assert r.status_code == 200, r.text
    for step, role in (("execute", "engineer"), ("verify", "verifier"), ("close", "closer")):
        r = client.post(f"/competition/sessions/{sid}/{step}", headers=_h(tickets[role]))
        assert r.status_code == 200, r.text
    assert r.json()["complete"] is True
    return sid


def test_finals_overview_projects_latest_closed_judge_session(client):
    sid = _run_full_session(client)
    body = client.get("/competition/finals/overview?lang=zh").json()
    source = body["mission"]["source"]
    assert source["kind"] == "JUDGE_SANDBOX_RUN"
    assert source["session_id"] == sid
    assert source["distinct_actors"] == 5
    assert source["closure_digest"]
    statuses = {row["id"]: row["status"] for row in body["mission"]["steps"]}
    assert statuses["authorize"] == "APPROVED"
    assert statuses["execute"] == "DRAFT_ONLY_NOT_SENT"
    assert statuses["verify"] == "DRAFT_VERIFIED"
    assert body["mission"]["document_workflow"] == "DRAFT_VERIFIED"
    # Document closure never claims physical remediation or external delivery.
    assert body["mission"]["physical_hazard"] == "REINSPECTION_NOT_PERFORMED"
    assert body["mission"]["external_delivery_performed"] is False
    assert body["scenario"]["data_boundary"] == "SYNTHETIC_COMPETITION_ONLY"


def test_finals_scorecard_carries_delivery_stage_not_score(client):
    body = client.get("/competition/finals/overview?lang=zh").json()
    stages = {row["id"]: row["stage"] for row in body["scorecard"]}
    assert set(stages.values()) <= {"VERIFIED", "BUILT", "ROADMAP", "LIVE"}
    assert stages["economic-impact"] != "VERIFIED"  # no audited ROI yet
    assert stages["overseas-promotion"] == "ROADMAP"
    assert sum(row["max_score"] for row in body["scorecard"]) == 100
    # The real-model and ROI claims stay explicitly unverified.
    assert body["business_impact"]["model_comparison"]["status"] == "NOT_RUN"
    assert body["business_impact"]["paired_roi"]["improvement_percent"] is None



def test_competition_model_route_is_validated():
    import pytest
    from app.config import Settings

    assert Settings(competition_model_route=" AUTO ").competition_model_route == "auto"
    with pytest.raises(ValueError):
        Settings(competition_model_route="gpt-free-for-all")
