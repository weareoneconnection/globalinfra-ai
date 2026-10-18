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
    assert body["generated_at"] != "live-request"


def test_submission_evidence_covers_v5_release_and_all_core_suites(client):
    response = client.get("/competition/submission-evidence?lang=zh")
    assert response.status_code == 200
    body = response.json()
    assert body["phase"] == "V5.1"
    assert body["release"]["product_version"] == "V5.1"
    assert body["release"]["passed_cases"] == 57
    assert body["release"]["total_cases"] == 57
    assert body["release"]["ci"]["api_tests_passed"] == 265
    assert [(row["passed_cases"], row["total_cases"]) for row in body["evaluation_suites"]] == [
        (30, 30), (12, 12), (15, 15),
    ]
    assert len(body["capabilities"]) == 6
    assert len(body["scorecard"]) == 10
    assert sum(row["max_score"] for row in body["scorecard"]) == 100


def test_submission_evidence_exposes_safe_model_and_lineage_metadata(client):
    body = client.get("/competition/submission-evidence").json()
    governance = body["governance"]
    assert len(governance["evidence_digest"]) == 64
    assert set(governance["dataset_hashes"]) == {
        "ai_outbound", "agent_organization", "assistant_dispatch",
    }
    assert all(len(value) == 64 for value in governance["dataset_hashes"].values())
    assert "api_key" not in str(governance["model_routing"]).lower()
    assert governance["external_delivery_performed"] is False


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
