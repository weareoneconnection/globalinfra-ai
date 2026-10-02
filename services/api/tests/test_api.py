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


def test_approval_flow_updates_case_and_verification_status(client):
    client.post(f"/cases/{SEEDED_CASE_ID}/analyze")
    approvals = client.get("/approvals").json()
    pending = next(a for a in approvals if a["case_id"] == SEEDED_CASE_ID and a["status"] == "PENDING")

    r = client.post(f"/approvals/{pending['id']}/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "APPROVED"

    detail = client.get(f"/cases/{SEEDED_CASE_ID}").json()
    assert detail["status"] == "APPROVED_FOR_ACTION"
    assert detail["verification"]["status"] == "PASS"


def test_approve_unknown_approval_returns_404(client):
    r = client.post("/approvals/999999/approve")
    assert r.status_code == 404
