"""P2 public finals read model must never expose tenant ROI or private documents."""
import json

import app.competition as competition_module
from app.database import SessionLocal
from app.models import PilotMeasurement


def test_finals_overview_maps_exact_official_rubric_and_synthetic_scenario(client):
    response = client.get("/competition/finals/overview?lang=zh")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema"] == "globalinfra.finals-mission.v1"
    assert body["edition"] == "P2_FINALS_PRESENTATION"
    assert body["scoring_standard"] == "C4AI_2026_FINAL_AI_OUTBOUND_11_ITEMS"
    assert body["scenario"]["synthetic"] is True
    assert body["scenario"]["data_boundary"] == "SYNTHETIC_COMPETITION_ONLY"
    assert body["mission"]["external_delivery_performed"] is False
    assert body["mission"]["project_safety_case_closed"] is False
    assert body["mission"]["physical_hazard"] == "REINSPECTION_NOT_PERFORMED"
    assert len(body["mission"]["steps"]) == 6
    assert [row["max_score"] for row in body["scorecard"]] == [
        10, 8, 7, 15, 10, 8, 7, 5, 8, 7, 15,
    ]
    assert sum(row["max_score"] for row in body["scorecard"]) == 100
    assert body["business_impact"]["model_comparison"]["status"] == "NOT_RUN"
    assert body["business_impact"]["model_comparison"]["verified_score"] is None
    assert body["business_impact"]["paired_roi"]["status"] == "NO_AUDITED_PUBLIC_RESULT"
    assert body["business_impact"]["paired_roi"]["improvement_percent"] is None
    assert body["country_adaptation"]["status"] == "CONFIGURATION_COMPARISON_ONLY"
    assert body["country_adaptation"]["first"]["code"] == "MY"
    assert body["country_adaptation"]["second"]["code"] == "AE"


def test_finals_public_projection_excludes_tenant_roi_details(client):
    secret = "NONPUBLIC-P2-ROI-TENANT-CASE-000"
    with SessionLocal() as db:
        row = PilotMeasurement(
            id="ROI-P2-PUBLIC-PROJECTION-TEST",
            organization_id="different-organization",
            project_id=1,
            metric_name="human_minutes_per_case",
            direction="LOWER",
            baseline_value=9001.0,
            assisted_value=1.0,
            unit="minutes",
            sample_size=1,
            evidence_ref=secret,
            evidence_digest="c" * 64,
            status="VERIFIED",
            recorded_by="oidc:recorded-by-another-org",
            verified_by="oidc:verified-by-another-org",
        )
        db.add(row)
        db.commit()
    try:
        response = client.get("/competition/finals/overview?lang=en")
        assert response.status_code == 200
        body = response.json()
        rendered = json.dumps(body)
        assert secret not in rendered
        assert row.id not in rendered
        assert "9001" not in rendered
        assert body["business_impact"]["paired_roi"]["baseline_minutes"] is None
        assert body["business_impact"]["paired_roi"]["assisted_minutes"] is None
    finally:
        with SessionLocal() as db:
            stored = db.get(PilotMeasurement, "ROI-P2-PUBLIC-PROJECTION-TEST")
            if stored is not None:
                db.delete(stored)
                db.commit()


def test_finals_release_fail_closed_without_artifact(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        competition_module,
        "RELEASE_EVIDENCE_PATH",
        tmp_path / "nonexistent-p2-signed-release.json",
    )
    response = client.get("/competition/finals/overview?lang=en")
    assert response.status_code == 200
    body = response.json()
    assert body["release"]["status"] == "UNVERIFIED"
    assert body["release"]["verified_cases"] == 0
    assert body["business_impact"]["model_comparison"]["status"] == "NOT_RUN"
    assert body["business_impact"]["paired_roi"]["improvement_percent"] is None
