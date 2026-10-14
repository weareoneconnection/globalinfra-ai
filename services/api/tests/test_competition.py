from app.competition import GOLDEN_CASE_ID


def test_competition_evaluation_is_reproducible_and_passes(client):
    response = client.get("/competition/evaluation?include_cases=true")
    assert response.status_code == 200
    body = response.json()
    assert body["suite"] == "AI_OUTBOUND_COMPETITION_EVIDENCE"
    assert body["total_cases"] == 30
    assert body["status"] == "PASSED"
    assert len(body["cases"]) == 30
    assert body["category_coverage"] == {
        "multilingual_event": 8,
        "regulation_permit": 8,
        "contract_claim": 6,
        "local_hse_training": 4,
        "twin_operation": 4,
    }
    assert all(body["gates"].values())


def test_golden_thread_requires_explicit_human_approval(client):
    blocked = client.post("/competition/golden-thread/run", json={"human_approval_confirmed": False})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "HUMAN_APPROVAL_REQUIRED"


def test_golden_thread_runs_existing_governed_execution_to_verified_receipts(client):
    before = client.get("/competition/golden-thread?lang=zh")
    assert before.status_code == 200
    assert before.json()["case"]["id"] == GOLDEN_CASE_ID
    assert before.json()["intake"]["country"] == "MY"
    assert before.json()["twin"]["interfaces"]

    response = client.post("/competition/golden-thread/run?lang=zh", json={
        "human_approval_confirmed": True,
        "approver": "Competition test operator",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["complete"] is True
    assert body["case"]["status"] == "CLOSED"
    assert body["run"]["human_approval_recorded"] is True
    assert body["run"]["external_delivery_performed"] is False
    assert body["receipts"]["execution"]["status"] == "SUCCEEDED"
    assert body["receipts"]["verification"]["status"] == "VERIFIED"
    assert all(body["receipts"]["verification"]["checks"].values())
    assert body["receipts"]["artifact"]["digest"] == body["receipts"]["execution"]["output_digest"]


def test_golden_thread_run_is_idempotent_after_close(client):
    response = client.post("/competition/golden-thread/run", json={
        "human_approval_confirmed": True,
        "approver": "Competition test operator",
    })
    assert response.status_code == 200
    assert response.json()["complete"] is True
    assert response.json()["action"]["status"] == "CLOSED"
