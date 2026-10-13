"""Integration tests against the real FastAPI app + seeded demo dataset.

These exercise the same route layer, dependency injection (``get_lang`` /
``get_db``) and SQLAlchemy models the running service uses, backed by a
throwaway SQLite database (see conftest.py) instead of mocks.
"""

SEEDED_CASE_ID = "CASE-2026-0182"


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_projects_are_localized_by_the_lang_query_param(client):
    en = client.get("/projects?lang=en").json()
    zh = client.get("/projects?lang=zh").json()
    assert len(en) >= 1 and len(zh) == len(en)
    my_en = next(p for p in en if p["country_code"] == "MY")
    my_zh = next(p for p in zh if p["country_code"] == "MY")
    assert my_en["country_name"] == "Malaysia"
    assert my_zh["country_name"] == "马来西亚"
    assert my_en["latitude"] == 3.139
    assert my_en["longitude"] == 101.687
    assert my_zh["location_name"] == "吉隆坡走廊"


def test_projects_default_to_english_without_a_lang_hint(client):
    r = client.get("/projects")
    assert r.status_code == 200
    assert r.json()[0]["country_name"] in ("Malaysia", "Indonesia", "Saudi Arabia")


def test_classify_endpoint_reaches_the_rule_based_classifier(client):
    r = client.post("/cases/classify", json={"text": "Worker observed near unprotected edge at elevated workface."})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "HSE"
    assert body["risk"] == "CRITICAL"


def test_case_detail_404_for_unknown_case(client):
    r = client.get("/cases/DOES-NOT-EXIST")
    assert r.status_code == 404


def test_analyze_unknown_case_returns_404(client):
    r = client.post("/cases/DOES-NOT-EXIST/analyze")
    assert r.status_code == 404


def test_analyze_case_is_idempotent(client):
    first = client.post(f"/cases/{SEEDED_CASE_ID}/analyze")
    assert first.status_code == 200
    detail_first = client.get(f"/cases/{SEEDED_CASE_ID}").json()

    second = client.post(f"/cases/{SEEDED_CASE_ID}/analyze")
    assert second.status_code == 200
    detail_second = client.get(f"/cases/{SEEDED_CASE_ID}").json()

    # Re-running analysis replaces prior runtime artifacts; it must not
    # accumulate duplicate evidence/agent-run rows (workflow.analyze_case
    # explicitly deletes-then-recreates them for this reason).
    assert len(detail_first["evidence"]) == len(detail_second["evidence"]) > 0
    assert len(detail_first["agent_runs"]) == len(detail_second["agent_runs"]) > 0
    assert detail_second["status"] == "AWAITING_APPROVAL"


def test_approval_does_not_execute_or_mark_verification_pass(client):
    client.post(f"/cases/{SEEDED_CASE_ID}/analyze")
    approvals = client.get("/approvals").json()
    pending = next(a for a in approvals if a["case_id"] == SEEDED_CASE_ID and a["status"] == "PENDING")
    action_id = pending["action_id"]

    blocked = client.post(f"/actions/{action_id}/execute")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "APPROVAL_REQUIRED"

    r = client.post(f"/approvals/{pending['id']}/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "APPROVED"

    detail = client.get(f"/cases/{SEEDED_CASE_ID}").json()
    assert detail["status"] == "APPROVED"
    assert detail["action"]["status"] == "APPROVED"
    assert detail["verification"]["status"] == "WARN"
    assert detail["verification_receipt"] is None
    assert detail["execution_receipt"] is None


def test_trusted_execution_requires_execution_before_independent_verification(client):
    case_id = "CASE-2026-0194"
    assert client.post(f"/cases/{case_id}/analyze").status_code == 200
    approvals = [a for a in client.get("/approvals").json() if a["case_id"] == case_id]
    action_id = approvals[0]["action_id"]
    assert len(approvals) == 2

    first = client.post(f"/approvals/{approvals[0]['id']}/approve")
    assert first.status_code == 200
    assert first.json()["case_status"] == "AWAITING_APPROVAL"
    assert client.post(f"/actions/{action_id}/execute").status_code == 409

    second = client.post(f"/approvals/{approvals[1]['id']}/approve")
    assert second.status_code == 200
    assert second.json()["case_status"] == "APPROVED"

    executed = client.post(f"/actions/{action_id}/execute", json={"executor": "test.executor"})
    assert executed.status_code == 200
    assert executed.json()["status"] == "EXECUTED"
    assert executed.json()["execution_receipt"]["status"] == "SUCCEEDED"
    artifact = executed.json()["execution_receipt"]["artifact"]
    assert artifact["digest"]
    assert artifact["ref"] == f"artifact://sha256/{artifact['digest']}"

    verified = client.post(f"/actions/{action_id}/verify", json={"verifier": "test.verifier"})
    assert verified.status_code == 200
    assert verified.json()["result"] == "PASS"
    assert verified.json()["verification_receipt"]["status"] == "VERIFIED"

    replay = client.post(f"/actions/{action_id}/execute")
    assert replay.status_code == 200
    assert replay.json()["idempotent"] is True

    closed = client.post(f"/actions/{action_id}/close")
    assert closed.status_code == 200
    assert closed.json()["status"] == "CLOSED"
    execute_after_close = client.post(f"/actions/{action_id}/execute")
    assert execute_after_close.status_code == 409
    assert execute_after_close.json()["detail"]["code"] == "ACTION_CLOSED"
    verify_after_close = client.post(f"/actions/{action_id}/verify")
    assert verify_after_close.status_code == 409
    assert verify_after_close.json()["detail"]["code"] == "ACTION_CLOSED"

    detail = client.get(f"/cases/{case_id}").json()
    assert detail["status"] == "CLOSED"
    assert detail["execution_receipt"]["status"] == "SUCCEEDED"
    assert detail["verification_receipt"]["status"] == "VERIFIED"


def test_reanalysis_invalidates_prior_approval_before_new_execution(client):
    case_id = "CASE-2026-0209"
    assert client.post(f"/cases/{case_id}/analyze").status_code == 200
    approval = next(a for a in client.get("/approvals").json() if a["case_id"] == case_id and a["status"] == "PENDING")
    action_id = approval["action_id"]
    assert client.post(f"/approvals/{approval['id']}/approve").status_code == 200

    rerun = client.post(f"/cases/{case_id}/analyze")
    assert rerun.status_code == 200
    refreshed = [a for a in client.get("/approvals").json() if a["case_id"] == case_id]
    assert all(a["status"] == "PENDING" for a in refreshed)
    assert client.get(f"/actions/{action_id}").json()["status"] == "AWAITING_APPROVAL"
    assert client.post(f"/actions/{action_id}/execute").status_code == 409


def test_approve_unknown_approval_returns_404(client):
    r = client.post("/approvals/999999/approve")
    assert r.status_code == 404
