from uuid import uuid4


EXPECTED_CHANNELS = {
    "event_work_order",
    "document_correspondence",
    "project_master",
    "enterprise_connector",
    "twin_model",
    "iot_telemetry",
}


def test_ingestion_catalog_has_six_distinct_domain_channels(client):
    response = client.get("/ingestion/catalog?lang=en")
    assert response.status_code == 200
    body = response.json()
    assert body["channel_count"] == 6
    assert {item["id"] for item in body["channels"]} == EXPECTED_CHANNELS
    assert "events are emitted only" in body["principle"]
    assert all(item["canonical_objects"] for item in body["channels"])


def test_ingestion_summary_exposes_seeded_demo_boundary_and_all_channels(client):
    response = client.get("/ingestion/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["active_channels"] == 6
    assert set(body["by_channel"]) == EXPECTED_CHANNELS
    assert body["records_accepted"] >= 6
    demo = [item for item in body["recent"] if item["status"] == "SYNTHETIC_DEMO"]
    assert demo
    assert all(item["lineage"]["provenance"] == "SYNTHETIC_DEMO" for item in demo)


def test_project_master_creates_project_and_traceable_receipt(client):
    code = f"MDM-{uuid4().hex[:8].upper()}"
    response = client.post("/ingestion/project-master?lang=en", json={
        "code": code,
        "name": "Unified ingestion test project",
        "country_code": "SG",
        "country_name": "Singapore",
        "domain": "Rail",
        "region": "APAC",
        "languages": ["English", "中文"],
        "risk_level": "LOW",
    })
    assert response.status_code == 201
    body = response.json()
    assert body["project"]["code"] == code
    assert body["ingestion_receipt"]["channel"] == "project_master"
    assert body["ingestion_receipt"]["target_type"] == "Project"
    assert body["ingestion_receipt"]["target_id"] == str(body["project"]["id"])


def test_text_and_document_intake_keep_separate_ingestion_channels(client):
    text = client.post("/intake/text?lang=en", json={
        "text": "Malaysia site inspection found an unsafe access route requiring immediate review.",
        "data_classification": "internal",
    })
    assert text.status_code == 200
    assert text.json()["ingestion_receipt"]["channel"] == "event_work_order"

    document = client.post(
        "/intake/document?lang=en&data_classification=internal",
        files={"file": ("owner-letter.txt", b"Malaysia owner letter requires a response within 48 hours.", "text/plain")},
    )
    assert document.status_code == 200
    receipt = document.json()["ingestion_receipt"]
    assert receipt["channel"] == "document_correspondence"
    assert receipt["target_type"] == "Case"


def test_receipts_can_be_filtered_by_channel_and_project(client):
    response = client.get("/ingestion/receipts?channel=twin_model&project_id=1")
    assert response.status_code == 200
    rows = response.json()
    assert rows
    assert all(row["channel"] == "twin_model" and row["project_id"] == 1 for row in rows)

    invalid = client.get("/ingestion/receipts?channel=everything_is_an_event")
    assert invalid.status_code == 422


def test_manual_work_order_honors_user_confirmed_project(client):
    response = client.post("/intake/text?lang=en", json={
        "text": "Drainage inspection work order\nType: Quality\nDeclared risk: HIGH\nDescription: Review concrete surface defects within 24 hours.",
        "project_id": 2,
        "entry_type": "work_order",
        "model_route": "auto",
        "data_classification": "internal",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["intake"]["project_routing_source"] == "USER_CONFIRMED"
    assert body["ingestion_receipt"]["project_id"] == 2
    assert body["ingestion_receipt"]["source_type"] == "work_order"
    detail = client.get(f"/cases/{body['case_id']}?lang=en").json()
    assert detail["project_name"] == "Trans-Nusantara Highway B"
