"""Field reports go through intake classification and the agent organization."""
from datetime import UTC, datetime
from uuid import uuid4

from app.field_ai import higher_risk


def _report(client, description, event_type="hse", severity="MEDIUM", twin_id=None):
    payload = {"observations": [{
        "client_id": f"field-test:{uuid4().hex}", "project_id": 1, "twin_id": twin_id,
        "event_type": event_type, "severity": severity, "description": description,
        "location": {}, "attachments": [], "captured_at": datetime.now(UTC).isoformat(),
    }]}
    body = client.post("/field/sync", json=payload).json()
    return body["results"][0]


def test_risk_is_never_lowered():
    assert higher_risk("MEDIUM", "CRITICAL") == "CRITICAL"
    assert higher_risk("HIGH", "LOW") == "HIGH"


def test_field_report_is_classified_raised_and_analyzed(client):
    result = _report(client, "Two workers at height at Pier P47 near an unprotected edge without fall protection.",
                     twin_id="TWIN-MYRAIL-V12-P47")
    reports = {r["id"]: r for r in client.get("/field/reports?lang=en").json()}
    report = reports[result["id"]]
    assert report["analysis_status"] == "ANALYZED"
    assert report["case"]["type"] == "HSE"
    assert report["risk_review"] == {"reported": "MEDIUM", "ai": "CRITICAL", "final": "CRITICAL", "raised": True}
    assert report["plan"] and report["plan"][-1]["source"] == "governance"
    case = client.get(f"/cases/{result['case_id']}").json()
    assert case["status"] == "AWAITING_APPROVAL" and case["action"] is not None


def test_reporter_category_guides_but_does_not_fix_the_type(client):
    result = _report(client, "Concrete crack 0.4 mm and honeycomb on the P52 column.", event_type="inspection", severity="LOW")
    report = next(r for r in client.get("/field/reports?lang=en").json() if r["id"] == result["id"])
    assert report["case"]["type"] == "Quality"
    assert report["risk_review"]["final"] == "MEDIUM" and report["risk_review"]["raised"] is True


def test_duplicate_sync_is_not_analyzed_twice(client):
    observation = {
        "client_id": f"field-test:{uuid4().hex}", "project_id": 1, "twin_id": None, "event_type": "delivery",
        "severity": "LOW", "description": "Supplier delivery of roof trusses delayed by six weeks on PO-7781.",
        "location": {}, "attachments": [], "captured_at": datetime.now(UTC).isoformat(),
    }
    first = client.post("/field/sync", json={"observations": [observation]}).json()["results"][0]
    second = client.post("/field/sync", json={"observations": [observation]}).json()["results"][0]
    assert first["created"] is True and second["created"] is False and first["case_id"] == second["case_id"]
    runs = [r for r in client.get("/agents/runs?limit=100").json() if r["case_id"] == first["case_id"]]
    assert len(runs) == 1
