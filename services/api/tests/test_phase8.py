from uuid import uuid4


def test_model_lineage_and_diff(client):
    plane = client.get("/twin/model-versions?project_id=1")
    assert plane.status_code == 200
    assert len(plane.json()["versions"]) >= 2
    assert plane.json()["external_adapters"]["ifc_converter"] == "NOT_CONFIGURED"
    diff = client.get("/twin/model-diff?project_id=1")
    assert diff.status_code == 200
    assert diff.json()["to"]
    assert diff.json()["evidence"]


def test_reference_conversion_pipeline(client):
    response = client.post("/twin/conversions", json={"project_id": 1, "input_ref": "s3://demo/model.ifc", "input_format": "IFC", "output_formats": ["GLTF", "3D_TILES"]})
    assert response.status_code == 201
    assert response.json()["status"] == "COMPLETED"
    assert response.json()["progress"] == 100


def test_one_click_project_factory(client):
    code = f"TEST-{uuid4().hex[:8].upper()}"
    response = client.post("/twin/projects/generate", json={"code": code, "name": "Phase 8 Test Project", "country_code": "CN", "domain": "Energy", "kind": "energy", "center": [121.47, 31.23]})
    assert response.status_code == 201
    body = response.json()
    assert body["objects"] == 3
    assert body["sources"] == 6
    manifest = client.get(f"/twin/demo-pack/{body['project_id']}/manifest")
    assert manifest.status_code == 200
    assert manifest.json()["coverage"] == "6/6"


def test_telemetry_history_ingest_and_sse(client):
    response = client.post("/twin/telemetry/ingest", json={"project_id": 1, "sensor_id": "SNS-VIB-AHU01", "value": 5.5})
    assert response.status_code == 202
    assert response.json()["status"] == "ACCEPTED"
    history = client.get("/twin/telemetry/history?project_id=1&limit=5")
    assert history.status_code == 200
    assert history.json()[0]["sensor_id"] == "SNS-VIB-AHU01"
    live = client.get("/twin/telemetry/live/1?events=1")
    assert live.status_code == 200
    assert "event: telemetry" in live.text


def test_grounded_copilot_and_showcase(client):
    response = client.post("/twin/copilot/query", json={"project_id": 1, "question": "Which asset has the highest risk?"})
    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is True
    assert body["requires_approval"] is True
    assert any(item["type"] == "TWIN_OBJECT" for item in body["citations"])
    showcase = client.get("/twin/showcase/1")
    assert showcase.status_code == 200
    assert [step["id"] for step in showcase.json()["steps"]] == ["8.1", "8.2", "8.3", "8.4", "8.5", "8.6", "8.7"]
