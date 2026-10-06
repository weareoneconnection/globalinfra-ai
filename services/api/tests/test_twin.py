"""End-to-end coverage for the V2.0 full-lifecycle digital twin."""


def test_twin_summary_reaches_phase_6(client):
    response = client.get("/twin/summary?project_id=1")
    assert response.status_code == 200
    body = response.json()
    assert body["maturity"] == "PHASE_6"
    assert body["objects"] >= 8
    assert body["mapped_objects"] == body["objects"]
    assert body["online_sensors"] >= 3
    assert len(body["layers"]) == 8


def test_twin_scene_connects_geometry_and_events(client):
    body = client.get("/twin/scene?project_id=1&lang=en").json()
    p47 = next(item for item in body["objects"] if item["id"] == "TWIN-MYRAIL-V12-P47")
    assert p47["ifc_guid"]
    assert p47["geometry_ref"].startswith("ifc://")
    assert any(event["twin_id"] == p47["id"] for event in body["events"])
    assert "IFC 4.3" in body["geometry_protocols"]


def test_twin_object_has_traceable_state_evidence_and_telemetry(client):
    response = client.get("/twin/objects/TWIN-MYRAIL-ST04-AHU01")
    assert response.status_code == 200
    body = response.json()
    assert body["state_history"][0]["evidence_ref"] == "BMS-ST04-2026"
    assert len(body["sensors"]) == 2
    assert body["events"][0]["evidence_refs"]


def test_4d_5d_controls_expose_schedule_and_cost_variance(client):
    rows = client.get("/twin/controls?project_id=1").json()
    p47 = next(row for row in rows if row["twin_id"] == "TWIN-MYRAIL-V12-P47")
    assert p47["schedule_variance_days"] == -8
    assert p47["cost_variance_m"] == 0.25


def test_commissioning_and_operations_bridge_handover(client):
    commissioning = client.get("/twin/commissioning?project_id=1").json()
    operations = client.get("/twin/operations?project_id=1").json()
    assert any(item["stage"] == "INTEGRATED_TEST" for item in commissioning)
    assert any(item["status"] == "WARNING" for item in operations["sensors"])
    assert any(item["work_type"] == "CONDITION_BASED" for item in operations["maintenance"])


def test_scenario_simulation_is_governed(client):
    response = client.post("/twin/scenarios/SCN-RECOVERY-V12/run?lang=zh", json={"adjustment_percent": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["execution_status"] == "AWAITING_APPROVAL"
    assert body["result"]["daysRecovered"] == 5.5
    assert "人工审批" in body["governance"]


def test_missing_twin_object_and_scenario_return_404(client):
    assert client.get("/twin/objects/NOT-FOUND").status_code == 404
    assert client.post("/twin/scenarios/NOT-FOUND/run", json={}).status_code == 404
