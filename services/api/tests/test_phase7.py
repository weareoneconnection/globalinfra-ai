from datetime import UTC, datetime


def test_phase7_capabilities_and_identity(client):
    capabilities = client.get("/platform/capabilities")
    assert capabilities.status_code == 200
    body = capabilities.json()
    assert body["stage"] == "PHASE_7_PRODUCTION_PILOT"
    assert set(body["capabilities"]) == {"7.1", "7.2", "7.3", "7.4", "7.5", "7.6", "7.7"}

    identity = client.get("/identity/me").json()
    assert identity["organization_id"] == "globalinfra-demo"
    assert "field_user" in identity["roles"]


def test_field_sync_is_idempotent_and_creates_case(client):
    payload = {
        "client_id": "mobile-device-001:event-001",
        "project_id": 1,
        "twin_id": "TWIN-MYRAIL-V12-P47",
        "event_type": "inspection",
        "severity": "HIGH",
        "description": "Crack width reading requires engineering review.",
        "location": {"lat": 3.139, "lng": 101.687, "accuracy_m": 8},
        "attachments": [{
            "name": "p47.jpg", "media_type": "image/jpeg", "size": 1200,
            "sha256": "a" * 64, "storage_ref": "s3://field/p47.jpg",
        }],
        "captured_at": datetime.now(UTC).isoformat(),
    }
    created = client.post("/field/observations", json=payload)
    assert created.status_code == 201
    assert created.json()["created"] is True
    assert created.json()["case_id"].startswith("CASE-FIELD-")
    assert created.json()["sync_status"] == "SYNCED"

    duplicate = client.post("/field/observations", json=payload)
    assert duplicate.status_code == 201
    assert duplicate.json()["created"] is False
    assert duplicate.json()["id"] == created.json()["id"]

    listing = client.get("/field/observations?project_id=1").json()
    assert any(item["client_id"] == payload["client_id"] for item in listing)


def test_field_sync_rejects_twin_from_other_project(client):
    payload = {
        "client_id": "mobile-device-001:event-bad-twin",
        "project_id": 2,
        "twin_id": "TWIN-MYRAIL-V12-P47",
        "event_type": "ncr", "severity": "MEDIUM",
        "description": "Twin and project mismatch must be rejected.",
        "captured_at": datetime.now(UTC).isoformat(),
    }
    assert client.post("/field/observations", json=payload).status_code == 422


def test_real_twin_source_registry(client):
    created = client.post("/twin/sources", json={
        "project_id": 1, "source_type": "IFC", "name": "Viaduct federated model",
        "uri": "s3://models/myrail-v12.ifc", "version": "REV-D",
        "coordinate_reference_system": "EPSG:32647", "checksum": "b" * 64,
        "metadata": {"ifc_schema": "IFC4.3"},
    })
    assert created.status_code == 201
    source_id = created.json()["id"]
    synced = client.post(f"/twin/sources/{source_id}/sync")
    assert synced.status_code == 200
    assert synced.json()["status"] == "SYNCHRONIZED"
    assert "Twin ID" in synced.json()["contract"]


def test_connector_plane_rejects_secrets_and_tracks_sync(client):
    rejected = client.post("/integrations/connectors", json={
        "connector_type": "primavera_p6", "name": "Unsafe", "config": {"password": "nope"},
    })
    assert rejected.status_code == 422

    created = client.post("/integrations/connectors", json={
        "connector_type": "primavera_p6", "name": "P6 Programme", "project_id": 1,
        "config": {"endpoint_alias": "P6_PROD", "schedule_id": "MYRAIL"},
    })
    assert created.status_code == 201
    connector_id = created.json()["id"]
    sync = client.post(f"/integrations/connectors/{connector_id}/sync", json={
        "cursor": "2026-10-13T00:00:00Z",
        "records": [
            {"external_id": "ACT-1", "object_type": "activity", "updated_at": "2026-10-13T00:00:00Z", "payload": {}},
            {"object_type": "activity", "payload": {}},
        ],
    })
    assert sync.status_code == 200
    assert sync.json()["records_written"] == 1
    assert sync.json()["records_rejected"] == 1


def test_ai_quality_gate_and_operational_endpoints(client):
    blocked = client.post("/ai/quality-runs", json={
        "suite": "engineering-grounding", "model_provider": "openai",
        "model_name": "configured-model", "score": 0.80, "minimum_score": 0.90,
        "metrics": {"citation_precision": 0.96, "unsupported_claim_rate": 0.03},
        "dataset_version": "2026.10",
    })
    assert blocked.status_code == 201
    assert blocked.json()["release_gate"] == "CLOSED"
    assert client.get("/readyz").json()["database"] == "ok"
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "globalinfra_http_requests_total" in metrics.text
    assert metrics.headers.get("x-request-id")


def test_mutation_writes_audit_event(client):
    response = client.post("/identity/register")
    assert response.status_code == 200
    events = client.get("/audit/events").json()
    assert any(event["action"].startswith("POST /identity/register") for event in events)
