"""Digital-twin closed loop: governed work orders and telemetry write back to the twin."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.phase8 import is_trusted_model_source
from app.twin import evaluate_scenario


def test_scenario_runs_are_deterministic_and_never_mutate_the_baseline(client):
    before = next(s for s in client.get("/twin/scenarios?project_id=1").json() if s["id"] == "SCN-RECOVERY-V12")
    first = client.post("/twin/scenarios/SCN-RECOVERY-V12/run", json={"adjustment_percent": 10}).json()
    second = client.post("/twin/scenarios/SCN-RECOVERY-V12/run", json={"adjustment_percent": 10}).json()
    after = next(s for s in client.get("/twin/scenarios?project_id=1").json() if s["id"] == "SCN-RECOVERY-V12")

    assert first["result"] == second["result"]
    assert first["run_id"] == second["run_id"]
    assert after["result"] == before["result"]
    assert first["result"]["daysRecovered"] == round(5 * 1.1 ** 0.7, 2)
    assert first["result"]["costDeltaM"] == round(.18 * 1.1, 2)
    assert first["result"]["confidence"] < before["result"]["confidence"]
    assert first["method"]["id"] == "elasticity-v1"


def test_scenario_model_caps_benefits_and_keeps_non_numeric_fields():
    result = evaluate_scenario({"failureRiskReduction": 90, "risk": "MEDIUM", "confidence": .9}, 25)
    assert result["failureRiskReduction"] == 95
    assert result["risk"] == "MEDIUM"
    assert evaluate_scenario({"daysRecovered": 5, "confidence": .84}, 0) == {"daysRecovered": 5, "confidence": .84}


@pytest.mark.parametrize("ref", [
    "https://httpbin.org/anything", "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/computeMetadata/v1/", "http://localhost:5432/",
    "file:///etc/passwd", "s3://bucket/../../secret",
])
def test_conversion_rejects_network_and_traversal_sources(client, ref):
    assert not is_trusted_model_source(ref)
    response = client.post("/twin/conversions", json={"project_id": 1, "input_ref": ref})
    assert response.status_code == 422


def test_model_lineage_lists_only_trusted_sources(client):
    assert client.post("/twin/conversions", json={"project_id": 1, "input_ref": "s3://demo/rev-d.ifc"}).status_code == 201
    plane = client.get("/twin/model-versions?project_id=1").json()
    assert "quarantined_versions" in plane
    assert all(is_trusted_model_source(v["change_summary"].get("source")) for v in plane["versions"])


def test_critical_telemetry_opens_one_twin_event_and_an_approval_gated_work_order(client):
    first = client.post("/twin/telemetry/ingest", json={"project_id": 1, "sensor_id": "SNS-STRAIN-P47", "value": 251}).json()
    second = client.post("/twin/telemetry/ingest", json={"project_id": 1, "sensor_id": "SNS-STRAIN-P47", "value": 255}).json()
    try:
        assert first["level"] == "CRITICAL"
        assert first["alert"]["event_created"] is True
        assert first["alert"]["maintenance_status"] == "AWAITING_APPROVAL"
        assert second["alert"]["event_created"] is False
        assert second["alert"]["event_id"] == first["alert"]["event_id"]

        detail = client.get("/twin/objects/TWIN-MYRAIL-V12-P47").json()
        event = next(e for e in detail["events"] if e["id"] == first["alert"]["event_id"])
        assert event["type"] == "THRESHOLD" and event["severity"] == "HIGH"
        assert any(s["source_system"] == "IOT_THRESHOLD:CRITICAL" for s in detail["state_history"])

        operations = client.get("/twin/operations?project_id=1").json()
        assert next(s for s in operations["sensors"] if s["id"] == "SNS-STRAIN-P47")["status"] == "CRITICAL"
        assert any(m["id"] == first["alert"]["maintenance_id"] for m in operations["maintenance"])
        assert client.get("/twin/summary?project_id=1").json()["sync_status"] == "LIVE"
    finally:
        normal = client.post("/twin/telemetry/ingest", json={"project_id": 1, "sensor_id": "SNS-STRAIN-P47", "value": 164}).json()
        assert normal["level"] == "NORMAL" and normal["alert"] is None


def test_live_stream_replays_stored_readings(client):
    live = client.get("/twin/telemetry/live/1?events=2")
    assert live.status_code == 200
    assert "REPLAY_OF_STORED_READINGS" in live.text


def test_field_work_order_is_written_back_to_the_twin_through_closure(client):
    report = client.post("/field/observations", json={
        "client_id": f"twin-loop:{uuid4().hex}", "project_id": 1, "twin_id": "TWIN-MYRAIL-V12-P47",
        "event_type": "inspection", "severity": "HIGH",
        "description": "Crack gauge on P47 shows widening; engineering review needed.",
        "location": {"lat": 3.139, "lng": 101.687, "accuracy_m": 8},
        "attachments": [], "captured_at": datetime.now(UTC).isoformat(),
    })
    assert report.status_code == 201
    case_id = report.json()["case_id"]

    def work_order_event():
        detail = client.get("/twin/objects/TWIN-MYRAIL-V12-P47").json()
        return next(e for e in detail["events"] if e["type"] == "WORK_ORDER" and case_id in e["evidence_refs"]), detail

    event, detail = work_order_event()
    assert event["status"] == "OPEN"
    status_before = detail["status"]

    assert client.post(f"/cases/{case_id}/analyze").status_code == 200
    approvals = [a for a in client.get("/approvals").json() if a["case_id"] == case_id and a["status"] == "PENDING"]
    assert approvals
    action_id = approvals[0]["action_id"]
    for approval in approvals:
        assert client.post(f"/approvals/{approval['id']}/approve").status_code == 200
    assert client.post(f"/actions/{action_id}/execute", json={"executor": "loop.executor"}).status_code == 200

    verified = client.post(f"/actions/{action_id}/verify", json={"verifier": "loop.verifier"}).json()
    assert verified["twin_sync"] == ["TWIN-MYRAIL-V12-P47"]
    event, detail = work_order_event()
    assert event["status"] == "VERIFIED"
    assert verified["verification_receipt"]["id"] in event["evidence_refs"]

    closed = client.post(f"/actions/{action_id}/close").json()
    assert closed["twin_sync"] == ["TWIN-MYRAIL-V12-P47"]
    event, detail = work_order_event()
    assert event["status"] == "CLOSED"
    # Paperwork does not change the asset's physical status.
    assert detail["status"] == status_before
    sources = [s["source_system"] for s in detail["state_history"]]
    for stage in ("OPEN", "VERIFIED", "CLOSED"):
        assert f"GOVERNED_WORK_ORDER:{stage}" in sources


def test_golden_thread_locates_the_element_named_in_the_work_order(client):
    body = client.get("/competition/golden-thread").json()
    assert body["twin"]["twin_id"] == "TWIN-MYRAIL-V12-P47"
    assert "work_order_events" in body["twin"]
