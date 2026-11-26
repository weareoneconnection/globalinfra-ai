from app.main import app
from app.database import SessionLocal
from app.models import KnowledgeDocument
from app.security import Principal, get_principal


def _principal(subject: str, roles: set[str], organization: str = "globalinfra-demo"):
    return Principal(
        subject=subject,
        organization_id=organization,
        roles=frozenset(roles),
        project_ids=frozenset({1}),
        display_name=subject,
        issuer="https://identity.example.test",
    )


def test_seeded_country_pack_is_not_misrepresented_as_expert_released(client):
    pack = client.get("/country-packs/MY").json()
    assert pack["status"] == "REVIEWED_DEMO"
    assert pack["release_gate"] == "CLOSED"
    assert pack["reviewed_by"].startswith("seed:")
    assert len(pack["source_digest"]) == 64

    blocked = client.post(
        "/country-packs/MY/review",
        json={
            "source_digest": pack["source_digest"],
            "review_note": "Reviewed against current authoritative sources.",
            "valid_days": 180,
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "AUTHENTICATED_EXPERT_REVIEW_REQUIRED"


def test_roi_claim_requires_independent_verifier_and_real_paired_data(client):
    from app.roi_evidence import PairedStudy, evidence_sha256

    recorder = _principal("oidc:pilot-recorder", {"project_manager", "verifier", "viewer"})
    verifier = _principal("oidc:independent-verifier", {"verifier", "viewer"})
    study = PairedStudy(
        schema_version="globalinfra.pilot-roi-paired.v1",
        project_id=1,
        metric_name="human_minutes_per_case",
        unit="minutes",
        source_type="AUTHORIZED_REAL",
        authorization_ref="approval://project-study-1",
        study_protocol_ref="protocol://paired-case-study-1",
        cases=[
            {"case_id": "T-001", "baseline_value": 100, "assisted_value": 40},
            {"case_id": "T-002", "baseline_value": 140, "assisted_value": 44},
        ],
    )
    digest = evidence_sha256(study)
    app.dependency_overrides[get_principal] = lambda: recorder
    try:
        created = client.post(
            "/pilot/roi-measurements",
            json={
                "project_id": 1,
                "metric_name": "human_minutes_per_case",
                "baseline_value": 120,
                "assisted_value": 42,
                "unit": "minutes",
                "sample_size": 2,
                "evidence_ref": "object://pilot-evidence/paired-study.json",
                "evidence_digest": digest,
            },
        )
        assert created.status_code == 201, created.text
        measurement = created.json()
        assert measurement["status"] == "RECORDED_UNVERIFIED"
        path = f"/pilot/roi-measurements/{measurement['id']}/verify"
        self_verify = client.post(path, json={
            "evidence_digest": digest,
            "evidence": study.model_dump(mode="json"),
        })
        assert self_verify.status_code == 409
        assert self_verify.json()["detail"]["code"] == "INDEPENDENT_VERIFIER_REQUIRED"

        app.dependency_overrides[get_principal] = lambda: verifier
        digest_only = client.post(path, json={"evidence_digest": digest})
        assert digest_only.status_code == 409
        assert digest_only.json()["detail"]["code"] == "RAW_PAIRED_EVIDENCE_REQUIRED"

        changed = study.model_dump(mode="json")
        changed["cases"][0]["assisted_value"] = 80
        mismatch = client.post(path, json={"evidence_digest": digest, "evidence": changed})
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"]["code"] == "EVIDENCE_DIGEST_MISMATCH"

        synthetic = study.model_copy(update={"source_type": "SYNTHETIC"})
        fake_record = client.post(path, json={
            "evidence_digest": digest, "evidence": synthetic.model_dump(mode="json"),
        })
        assert fake_record.status_code == 409
        assert fake_record.json()["detail"]["code"] == "EVIDENCE_DIGEST_MISMATCH"

        wrong_values = study.model_copy(update={"cases": [
            study.cases[0].model_copy(update={"baseline_value": 110}),
            study.cases[1],
        ]})
        changed_digest = evidence_sha256(wrong_values)
        with SessionLocal() as db:
            from app.models import PilotMeasurement
            stored = db.get(PilotMeasurement, measurement["id"])
            stored.evidence_digest = changed_digest
            db.commit()
        bad_mean = client.post(path, json={
            "evidence_digest": changed_digest,
            "evidence": wrong_values.model_dump(mode="json"),
        })
        assert bad_mean.status_code == 409
        assert bad_mean.json()["detail"]["code"] == "ROI_RECOMPUTATION_FAILED"

        with SessionLocal() as db:
            from app.models import PilotMeasurement
            stored = db.get(PilotMeasurement, measurement["id"])
            stored.evidence_digest = digest
            db.commit()
        verified = client.post(path, json={
            "evidence_digest": digest,
            "evidence": study.model_dump(mode="json"),
        })
        assert verified.status_code == 200, verified.text
        assert verified.json()["status"] == "VERIFIED"
        assert verified.json()["verified_by"] == verifier.subject
        assert verified.json()["improvement_percent"] == 65.0

        summary = client.get("/pilot/roi-summary?project_id=1")
        assert summary.status_code == 200
        assert summary.json()["status"] == "VERIFIED_RESULTS_AVAILABLE"
        assert summary.json()["claimable_measurements"] >= 1
        assert "NOT independent proof" in summary.json()["boundary"]
    finally:
        app.dependency_overrides.pop(get_principal, None)


def test_roi_rejects_duplicate_case_ids_and_synthetic_sources(client):
    from app.roi_evidence import PairedStudy, evidence_sha256

    verifier = _principal("oidc:roi-verifier", {"verifier", "viewer"})
    recorder = _principal("oidc:roi-recorder", {"project_manager", "viewer"})
    study = {
        "schema_version": "globalinfra.pilot-roi-paired.v1",
        "project_id": 1, "metric_name": "human_minutes_per_case", "unit": "minutes",
        "source_type": "SYNTHETIC",
        "authorization_ref": "synthetic://authorized-study",
        "study_protocol_ref": "protocol://synthetic-study",
        "cases": [
            {"case_id": "S-1", "baseline_value": 120, "assisted_value": 40},
        ],
    }
    digest = evidence_sha256(PairedStudy(**study))
    app.dependency_overrides[get_principal] = lambda: recorder
    try:
        created = client.post("/pilot/roi-measurements", json={
            "project_id": 1, "metric_name": "human_minutes_per_case",
            "baseline_value": 120, "assisted_value": 40, "unit": "minutes",
            "sample_size": 1, "evidence_ref": "synthetic://paired-data",
            "evidence_digest": digest,
        })
        assert created.status_code == 201
        path = f"/pilot/roi-measurements/{created.json()['id']}/verify"
        app.dependency_overrides[get_principal] = lambda: verifier
        resp = client.post(path, json={"evidence_digest": digest, "evidence": study})
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "REAL_AUTHORIZED_SOURCE_REQUIRED"
        duplicate = dict(study)
        duplicate["cases"] = [study["cases"][0], study["cases"][0]]
        resp = client.post(path, json={"evidence_digest": digest, "evidence": duplicate})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_principal, None)


def test_project_and_case_lists_are_tenant_scoped(client):
    outsider = _principal(
        "oidc:outside", {"viewer"}, organization="different-organization"
    )
    app.dependency_overrides[get_principal] = lambda: outsider
    try:
        assert client.get("/projects").json() == []
        assert client.get("/cases").json() == []
        assert client.get("/approvals").json() == []
        assert client.get("/actions").json() == []
        assert client.get("/twin/summary").json()["objects"] == 0
        assert client.get("/twin/scene?project_id=1").status_code == 404
        assert client.get("/twin/objects/TWIN-MYRAIL-V12-P47").status_code == 404
        assert client.get("/twin/demo-pack/1/manifest").status_code == 404
        assert client.get("/cases/CASE-2026-0182/agent-run").status_code == 404
        assert client.get("/agents/runs").json() == []
        pack = client.get("/country-packs/MY").json()
        assert pack["project_count"] == 0
        assert pack["projects"] == []
    finally:
        app.dependency_overrides.pop(get_principal, None)


def test_project_knowledge_is_hidden_from_other_tenants(client):
    with SessionLocal() as db:
        document = KnowledgeDocument(
            title={"en": "Tenant secret procedure", "zh": "租户保密程序"},
            category={"en": "Project", "zh": "项目"},
            jurisdiction={"en": "Project", "zh": "项目"},
            language={"en": "English", "zh": "英语"},
            source_ref="TENANT-SECRET-V6-TEST",
            content={"en": "Confidential project procedure.", "zh": "保密项目程序。"},
            summary={"en": "Private test record", "zh": "私有测试记录"},
            project_id=1,
            confidentiality="CONFIDENTIAL",
            status="CURRENT",
        )
        db.add(document)
        db.commit()
        document_id = document.id

    outsider = _principal(
        "oidc:outside-knowledge", {"viewer"}, organization="different-organization"
    )
    app.dependency_overrides[get_principal] = lambda: outsider
    try:
        assert client.get(f"/knowledge/{document_id}").status_code == 404
        search = client.get("/knowledge/search?q=Tenant+secret+procedure").json()
        assert all(row["id"] != document_id for row in search["results"])
        legacy = client.get("/knowledge?query=Tenant+secret+procedure").json()
        assert all(row["id"] != document_id for row in legacy)
    finally:
        app.dependency_overrides.pop(get_principal, None)
        with SessionLocal() as db:
            row = db.get(KnowledgeDocument, document_id)
            if row is not None:
                db.delete(row)
                db.commit()
