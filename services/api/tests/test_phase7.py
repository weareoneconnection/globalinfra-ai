from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import hashlib
import hmac
import json
from uuid import uuid4

from sqlalchemy import func, select
from starlette.requests import Request

from app.database import SessionLocal
from app.main import app
from app.config import settings
from app.models import (
    AIQualityRun,
    Connector,
    FieldObservation,
    IngestionReceipt,
    PilotMeasurement,
    Project,
    TwinModelVersion,
    TwinObject,
    TwinSensor,
    TwinSource,
    TwinTelemetryReading,
)
from app.security import Principal, get_principal
from app.phase7 import _connector_webhook_key
from app import operations


def test_phase7_capabilities_and_identity(client):
    capabilities = client.get("/platform/capabilities")
    assert capabilities.status_code == 200
    body = capabilities.json()
    assert body["stage"] == "PHASE_10_1_UNIFIED_INGESTION"
    assert {"7.1", "7.7", "8.1", "8.7", "9.1", "10.1", "V6.1"}.issubset(body["capabilities"])

    identity = client.get("/identity/me").json()
    assert identity["organization_id"] == "globalinfra-demo"
    assert "field_user" in identity["roles"]


def test_platform_capability_counts_are_tenant_and_project_scoped(client):
    baseline = client.get("/platform/capabilities").json()["counts"]
    suffix = uuid4().hex
    project_id = 1_000_000 + int(suffix[:6], 16)
    organization_id = f"foreign-{suffix[:12]}"
    now = datetime.now(UTC).replace(tzinfo=None)
    project = Project(
        id=project_id,
        organization_id=organization_id,
        code=f"FOREIGN-{suffix[:12]}",
        name={"en": "Foreign project"},
        country_code="ZZ",
        country_name={"en": "Synthetic"},
        domain={"en": "Test"},
        region="isolated",
        languages=["English"],
    )
    twin = TwinObject(
        id=f"TWIN-{suffix}", project_id=project_id,
        object_type="asset", name={"en": "Foreign asset"},
        lifecycle_stage="construction", status="ACTIVE",
    )
    sensor = TwinSensor(
        id=f"SNS-{suffix[:24]}", twin_id=twin.id, sensor_type="test",
        unit="u", threshold_warning=1.0, threshold_critical=2.0,
        latest_value=0.5,
    )
    rows = [
        FieldObservation(
            id=f"FO-{suffix}", client_id=f"foreign:{suffix}",
            organization_id=organization_id, project_id=project_id,
            event_type="inspection", severity="LOW", description="Foreign tenant",
            reporter_id="foreign:user", captured_at=now,
        ),
        TwinSource(
            id=f"TS-{suffix}", organization_id=organization_id,
            project_id=project_id, source_type="IFC", name="Foreign source",
            uri="s3://foreign/model.ifc", version="1",
        ),
        Connector(
            id=f"CON-{suffix}", organization_id=organization_id,
            project_id=project_id, connector_type="primavera_p6",
            name="Foreign connector",
        ),
        AIQualityRun(
            id=f"AIQ-{suffix}", organization_id=organization_id,
            suite="foreign", model_provider="mock", model_name="mock",
            status="PASSED", score=1.0, dataset_version="test",
        ),
        TwinModelVersion(
            id=f"TMV-{suffix}", project_id=project_id, version="1",
            format="GLTF", status="READY", checksum="a" * 64,
            uri="s3://foreign/model.gltf",
        ),
        TwinTelemetryReading(
            project_id=project_id, sensor_id=sensor.id, twin_id=twin.id,
            value=0.5, unit="u", sampled_at=now,
        ),
        IngestionReceipt(
            id=f"IR-{suffix}", organization_id=organization_id,
            project_id=project_id, channel="test", source_type="test",
            status="ACCEPTED", target_type="test",
        ),
        PilotMeasurement(
            id=f"PM-{suffix}", organization_id=organization_id,
            project_id=project_id, metric_name="test", direction="lower",
            baseline_value=2.0, assisted_value=1.0, unit="u", sample_size=1,
            evidence_ref="test", evidence_digest="b" * 64,
            recorded_by="foreign:user",
        ),
    ]
    db = SessionLocal()
    db.add_all([project, twin, sensor, *rows])
    db.commit()
    try:
        # A row in every counted table belonging to another tenant must not
        # move any statistic visible to the demo tenant.
        assert client.get("/platform/capabilities").json()["counts"] == baseline

        scoped = Principal(
            subject="project-one:user",
            organization_id="globalinfra-demo",
            roles=frozenset({"viewer"}),
            project_ids=frozenset({1}),
            issuer="test-oidc",
        )
        app.dependency_overrides[get_principal] = lambda: scoped
        counts = client.get("/platform/capabilities").json()["counts"]
        expected = {
            "field_observations": db.scalar(select(func.count(FieldObservation.id)).where(
                FieldObservation.organization_id == "globalinfra-demo",
                FieldObservation.project_id == 1,
            )) or 0,
            "twin_sources": db.scalar(select(func.count(TwinSource.id)).where(
                TwinSource.organization_id == "globalinfra-demo", TwinSource.project_id == 1,
            )) or 0,
            "connectors": db.scalar(select(func.count(Connector.id)).where(
                Connector.organization_id == "globalinfra-demo", Connector.project_id == 1,
            )) or 0,
            "ai_quality_runs": db.scalar(select(func.count(AIQualityRun.id)).where(
                AIQualityRun.organization_id == "globalinfra-demo",
            )) or 0,
            "model_versions": db.scalar(select(func.count(TwinModelVersion.id)).join(
                Project, Project.id == TwinModelVersion.project_id,
            ).where(Project.organization_id == "globalinfra-demo", TwinModelVersion.project_id == 1)) or 0,
            "telemetry_readings": db.scalar(select(func.count(TwinTelemetryReading.id)).join(
                Project, Project.id == TwinTelemetryReading.project_id,
            ).where(Project.organization_id == "globalinfra-demo", TwinTelemetryReading.project_id == 1)) or 0,
            "ingestion_receipts": db.scalar(select(func.count(IngestionReceipt.id)).where(
                IngestionReceipt.organization_id == "globalinfra-demo", IngestionReceipt.project_id == 1,
            )) or 0,
            "pilot_measurements": db.scalar(select(func.count(PilotMeasurement.id)).where(
                PilotMeasurement.organization_id == "globalinfra-demo", PilotMeasurement.project_id == 1,
            )) or 0,
        }
        assert counts == expected
    finally:
        app.dependency_overrides.pop(get_principal, None)
        for row in reversed(rows):
            db.delete(row)
        db.delete(sensor)
        db.delete(twin)
        db.delete(project)
        db.commit()
        db.close()


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"field-photo"


def test_field_sync_is_idempotent_and_creates_case(client):
    upload = client.post(
        "/field/media",
        data={"project_id": "1"},
        files={"file": ("p47.jpg", JPEG, "image/jpeg")},
    ).json()
    payload = {
        "client_id": "mobile-device-001:event-001",
        "project_id": 1,
        "twin_id": "TWIN-MYRAIL-V12-P47",
        "event_type": "inspection",
        "severity": "HIGH",
        "description": "Crack width reading requires engineering review.",
        "location": {"lat": 3.139, "lng": 101.687, "accuracy_m": 8},
        "attachments": [{
            "name": "p47.jpg", "media_type": "image/jpeg", "size": upload["size"],
            "sha256": upload["sha256"], "storage_ref": upload["storage_ref"],
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


def test_field_sync_is_idempotent_under_concurrent_retries(client):
    client_id = f"mobile-race:{uuid4().hex}"
    payload = {
        "observations": [{
            "client_id": client_id,
            "project_id": 1,
            "event_type": "inspection",
            "severity": "MEDIUM",
            "description": "Concurrent offline retry must converge on one observation.",
            "captured_at": datetime.now(UTC).isoformat(),
        }],
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.post("/field/sync", json=payload), range(2)))

    assert [response.status_code for response in responses] == [200, 200]
    results = [response.json()["results"][0] for response in responses]
    assert len({result["id"] for result in results}) == 1
    assert sum(result["created"] for result in results) == 1


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


def test_every_project_has_a_complete_downloadable_synthetic_twin_pack(client):
    expected = {"IFC", "GLTF", "3D_TILES", "GEOJSON", "WMS", "IOT"}
    for project_id in (1, 2, 3):
        manifest = client.get(f"/twin/demo-pack/{project_id}/manifest")
        assert manifest.status_code == 200
        body = manifest.json()
        assert body["coverage"] == "6/6"
        assert body["provenance"] == "SYNTHETIC_DEMO"
        assert {item["type"] for item in body["artifacts"]} == expected
        assert body["twin_ids"]

        sources = client.get(f"/twin/sources?project_id={project_id}").json()
        assert expected.issubset({item["source_type"] for item in sources})
        assert all(item["status"] == "SYNTHETIC_DEMO" for item in sources if item["source_type"] in expected and "synthetic instance" in item["name"])

        ifc = client.get(f"/twin/demo-pack/{project_id}/model.ifc")
        assert ifc.status_code == 200
        assert ifc.text.startswith("ISO-10303-21;")
        assert "SYNTHETIC_DEMO" == ifc.headers["x-data-provenance"]

        gltf = client.get(f"/twin/demo-pack/{project_id}/model.gltf").json()
        assert gltf["asset"]["version"] == "2.0"
        assert all("twin_id" in node["extras"] for node in gltf["nodes"])

        tiles = client.get(f"/twin/demo-pack/{project_id}/tileset.json").json()
        assert tiles["asset"]["version"] == "1.1"
        assert tiles["root"]["content"]["uri"] == "model.gltf"

        geojson = client.get(f"/twin/demo-pack/{project_id}/features.geojson")
        assert geojson.headers["content-type"].startswith("application/geo+json")
        assert geojson.json()["type"] == "FeatureCollection"

        capabilities = client.get(f"/twin/demo-pack/{project_id}/wms")
        assert "WMS_Capabilities" in capabilities.text
        assert client.get(f"/twin/demo-pack/{project_id}/wms?request=GetMap").headers["content-type"].startswith("image/svg+xml")

        telemetry = client.get(f"/twin/demo-pack/{project_id}/iot/telemetry").json()
        assert telemetry["readings"]
        assert telemetry["provenance"] == "SYNTHETIC_DEMO"


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


def test_connector_webhook_signature_is_scoped_to_one_connector(client, monkeypatch):
    monkeypatch.setattr(
        settings, "connector_webhook_secret", "connector-root-secret-at-least-32-bytes"
    )
    connector_ids = []
    for name in ("P6 A", "P6 B"):
        response = client.post("/integrations/connectors", json={
            "connector_type": "primavera_p6", "name": name, "project_id": 1,
            "config": {"endpoint_alias": name.replace(" ", "_")},
        })
        assert response.status_code == 201
        connector_ids.append(response.json()["id"])
    payload = {
        "cursor": "2026-11-10T00:00:00Z",
        "records": [{
            "external_id": "ACT-WEBHOOK", "object_type": "activity",
            "updated_at": "2026-11-10T00:00:00Z", "payload": {},
        }],
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(
        _connector_webhook_key(connector_ids[0]), body, hashlib.sha256
    ).hexdigest()
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "require_api_key", True)
    try:
        accepted = client.post(
            f"/integrations/webhooks/{connector_ids[0]}", content=body,
            headers={"content-type": "application/json", "x-globalinfra-signature": f"sha256={signature}"},
        )
        cross_connector = client.post(
            f"/integrations/webhooks/{connector_ids[1]}", content=body,
            headers={"content-type": "application/json", "x-globalinfra-signature": f"sha256={signature}"},
        )
        assert accepted.status_code == 200
        assert cross_connector.status_code == 401
    finally:
        monkeypatch.setattr(settings, "auth_mode", "disabled")
        monkeypatch.setattr(settings, "require_api_key", False)


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


def test_fast_launch_readyz_is_200_but_discloses_degraded_controls(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "railway_environment", "")
    monkeypatch.setattr(settings, "competition_fast_launch", True)
    monkeypatch.setattr(
        "app.main.production_readiness",
        lambda: {
            "status": "NOT_READY",
            "controls": {
                "production_database": True,
                "enterprise_identity": False,
                "object_storage": False,
            },
        },
    )
    monkeypatch.setattr(
        "app.main.audit_health_snapshot",
        lambda: {
            "status": "ok", "consecutive_failures": 0,
            "failures_total": 0, "outbox_enqueued_total": 0,
            "outbox_failures_total": 0,
        },
    )

    response = client.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["readiness_class"] == "DEGRADED_COMPETITION"
    assert body["release"] == "NOT_READY"
    assert body["temporary_exceptions"] == [
        "enterprise_identity", "object_storage"
    ]


def test_mutation_writes_audit_event(client):
    response = client.post("/identity/register")
    assert response.status_code == 200
    events = client.get("/audit/events").json()
    assert any(event["action"].startswith("POST /identity/register") for event in events)


def test_audit_failure_is_counted_and_sent_to_durable_outbox(monkeypatch):
    class BrokenSession:
        def __enter__(self):
            raise RuntimeError("primary audit database unavailable")

        def __exit__(self, *_args):
            return False

    queued = []
    monkeypatch.setattr(operations, "SessionLocal", lambda: BrokenSession())
    monkeypatch.setattr(
        operations, "_enqueue_audit_outbox", lambda event: queued.append(event) is None
    )
    monkeypatch.setattr(operations, "_audit_consecutive_failures", 0)
    monkeypatch.setattr(operations, "_audit_write_failures_total", 0)
    monkeypatch.setattr(operations, "_audit_outbox_enqueued_total", 0)
    monkeypatch.setattr(operations, "_audit_outbox_failures_total", 0)
    request = Request({
        "type": "http", "method": "POST", "path": "/cases/classify",
        "headers": [], "query_string": b"", "server": ("test", 80),
        "client": ("test", 1234), "scheme": "http",
    })
    request.state.principal = Principal(
        subject="audit:test", organization_id="globalinfra-demo",
        roles=frozenset({"viewer"}), project_ids=frozenset({1}),
    )

    operations._write_audit(request, "request-audit-failure", 201, 4.2)

    health = operations.audit_health_snapshot()
    assert health["status"] == "degraded"
    assert health["failures_total"] == 1
    assert health["outbox_enqueued_total"] == 1
    assert health["outbox_failures_total"] == 0
    assert queued[0]["request_id"] == "request-audit-failure"


def test_redis_audit_outbox_writes_replayable_event(monkeypatch):
    import redis

    calls = []

    class FakeRedis:
        def xadd(self, stream, values, **options):
            calls.append((stream, values, options))

        def close(self):
            calls.append(("closed", {}, {}))

    monkeypatch.setattr(settings, "queue_url", "redis://audit-queue.test/0")
    monkeypatch.setattr(redis.Redis, "from_url", lambda *_args, **_kwargs: FakeRedis())

    assert operations._enqueue_audit_outbox({"id": "AUD-1", "detail": {"status_code": 201}})
    assert calls[0][0] == "globalinfra:audit-outbox:v1"
    assert json.loads(calls[0][1]["event"])["id"] == "AUD-1"
    assert calls[0][2]["maxlen"] == 100_000


def test_audit_failure_degrades_production_readiness(client, monkeypatch):
    monkeypatch.setattr(operations, "_audit_consecutive_failures", 1)

    readiness = client.get("/platform/production-readiness").json()

    assert readiness["controls"]["audit_persistence"] is False
    assert readiness["audit"]["status"] == "degraded"
    assert readiness["status"] == "NOT_READY"


def test_rate_limit_returns_429(client, monkeypatch):
    from collections import defaultdict, deque
    from app import operations
    from app.config import settings
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1)
    monkeypatch.setattr(operations, "_rate_windows", defaultdict(deque))
    assert client.get("/projects").status_code == 200
    limited = client.get("/projects")
    assert limited.status_code == 429
    assert limited.json()["detail"] == "Rate limit exceeded" and limited.headers["Retry-After"] == "60"
