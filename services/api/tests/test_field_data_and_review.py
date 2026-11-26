"""Authorized field-data intake and expert review records."""
import csv
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.field_data import (
    FIELD_DOCUMENT_TYPE, AuthorizationError, redact, seed_field_records, validate_authorization,
)
from app.knowledge_review import CLAUSE_STATUS, latest_reviews, review_summary, validate_review
from app.models import KnowledgeDocument

ROOT = Path(__file__).resolve().parents[3]


def _authorization(**overrides):
    today = date.today()
    record = {
        "authorization_id": "AUTH-TEST-01", "grantor_organisation": "Contractor A", "grantor_role": "Project Director",
        "granted_on": (today - timedelta(days=1)).isoformat(), "expires_on": (today + timedelta(days=30)).isoformat(),
        "purpose": "test", "permitted_uses": ["competition_demo"], "document_types": ["CORRESPONDENCE"],
        "countries": ["MY"], "evidence_ref": "test fixture",
    }
    record.update(overrides)
    return record


def test_redaction_removes_identifiers_and_keeps_counts_only():
    text = ("Dear Encik Ahmad bin Ali, call +60 12-345 6789 or mail pm@contractor-a.my. "
            "NRIC 850101-14-5678, NIK 3171234567890123, account no. 5140 1234 5678, passport A12345678. "
            "Real Builders Sdn Bhd will resubmit. Copy: Siti Rahmah.")
    result = redact(text, names=["Siti Rahmah"], aliases={"Real Builders Sdn Bhd": "Contractor A"})
    for leaked in ("Ahmad", "345 6789", "pm@", "850101", "3171234567890123", "5140 1234", "A12345678", "Real Builders", "Siti"):
        assert leaked not in result.text, leaked
    assert "Contractor A" in result.text and "[PERSON]" in result.text
    assert result.counts["PERSON"] == 2 and result.counts["EMAIL"] == 1 and result.counts["MY_NRIC"] == 1
    assert all(isinstance(n, int) for n in result.counts.values())


@pytest.mark.parametrize("overrides, message", [
    ({"evidence_ref": ""}, "missing"),
    ({"expires_on": (date.today() - timedelta(days=1)).isoformat()}, "expired"),
    ({"granted_on": (date.today() + timedelta(days=3)).isoformat()}, "not yet"),
    ({"permitted_uses": ["marketing"]}, "permitted_uses"),
])
def test_authorization_must_be_complete_current_and_in_scope(overrides, message):
    with pytest.raises(AuthorizationError, match=message):
        validate_authorization(_authorization(**overrides))
    with pytest.raises(AuthorizationError, match="outside"):
        validate_authorization(_authorization(), document_type="NCR")


def test_field_records_seed_as_confidential_project_documents_and_expire(client, tmp_path):
    record = {
        "record_id": "FIELD-AUTH-TEST-01-CORRESPONDENCE-0001", "project_code": "MY-RAIL-A", "country": "MY",
        "document_type": "CORRESPONDENCE", "title": "Letter on resubmission", "text": "Contractor A will resubmit the method statement.",
        "redacted_sha256": "0" * 64, "authorization": _authorization(), "imported_at": "2026-11-26T00:00:00",
    }
    (tmp_path / "field_records.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    with SessionLocal() as db:
        assert seed_field_records(db, tmp_path) == 1
        db.commit()
        doc = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.source_ref == record["record_id"]))
        assert doc.document_type == FIELD_DOCUMENT_TYPE and doc.confidentiality == "CONFIDENTIAL" and doc.project_id
        assert "AUTHORIZED_DEIDENTIFIED" in doc.tags
    # Visible to members of the project it belongs to, never as a public row.
    member = client.get("/knowledge/search", params={"q": "resubmit method statement", "document_type": FIELD_DOCUMENT_TYPE}).json()
    assert any(hit.get("source_ref") == record["record_id"] for hit in member["results"])

    record["authorization"] = _authorization(expires_on=(date.today() - timedelta(days=1)).isoformat())
    (tmp_path / "field_records.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    with SessionLocal() as db:
        assert seed_field_records(db, tmp_path) == 0
        db.commit()
        assert db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.source_ref == record["record_id"])) is None


def test_intake_refuses_raw_input_inside_the_repository(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps(_authorization()), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "field_data_intake.py"), "--input", str(ROOT / "docs"), "--authorization", str(auth),
         "--project-code", "MY-RAIL-A", "--country", "MY", "--document-type", "CORRESPONDENCE", "--out", str(tmp_path / "out")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2 and "outside the repository" in result.stderr


def test_intake_redacts_and_reports_without_values(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "letter_01.txt").write_text("Mr. Tan Wei will inspect. Contact tan@example.com.", encoding="utf-8")
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps(_authorization()), encoding="utf-8")
    out = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "field_data_intake.py"), "--input", str(raw), "--authorization", str(auth),
         "--project-code", "MY-RAIL-A", "--country", "MY", "--document-type", "CORRESPONDENCE", "--out", str(out)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    stored = (out / "field_records.jsonl").read_text(encoding="utf-8")
    report = (out / "redaction_report.json").read_text(encoding="utf-8")
    assert "Tan Wei" not in stored and "tan@example.com" not in stored
    assert "Tan" not in report and "example.com" not in report
    assert json.loads(report)["redactions"] == {"PERSON": 1, "EMAIL": 1}


def _review(item_id, verdict, day, **extra):
    return {
        "item_type": "clause", "item_id": item_id, "verdict": verdict, "packet_id": "P1", "reviewer_role": "Construction lawyer",
        "reviewer_qualification": "Advocate & Solicitor", "reviewer_organisation_type": "Law firm", "reviewed_on": day,
        "evidence_ref": "signed cover sheet", **extra,
    }


def test_review_records_need_reviewer_evidence_and_reasons():
    with pytest.raises(ValueError, match="evidence_ref"):
        validate_review(_review("MY-X", "ACCURATE", "2026-11-01", evidence_ref=""))
    with pytest.raises(ValueError, match="correction or comment"):
        validate_review(_review("MY-X", "INACCURATE", "2026-11-01"))
    assert CLAUSE_STATUS["INACCURATE"][1] != "CURRENT"


def test_latest_review_wins_and_summary_counts_only_real_records():
    rows = [_review("A", "INACCURATE", "2026-11-01", comment="wrong section"), _review("A", "ACCURATE", "2026-11-20"), _review("B", "ACCURATE", "2026-11-02")]
    assert latest_reviews("clause", rows)["A"]["verdict"] == "ACCURATE"
    summary = review_summary(["A", "B", "C"], ["T1"], rows)
    assert summary["clauses_reviewed"] == 2 and summary["clauses_total"] == 3 and summary["terms_reviewed"] == 0
    assert review_summary(["A"], [], [])["records"] == 0


def test_manifest_reports_no_reviews_until_a_packet_is_imported(client):
    reviews = client.get("/knowledge/library").json()["reviews"]
    assert reviews["records"] == 0 and reviews["clauses_reviewed"] == 0 and reviews["clauses_total"] >= 180


def test_review_packet_is_stratified_and_blank(tmp_path):
    out = tmp_path / "packet.csv"
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_review_packet.py"), "--country", "ID", "--kind", "clause",
                             "--per-instrument", "2", "--packet-id", "T", "--out", str(out)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert len({row["instrument"] for row in rows}) == 5 and len(rows) == 10
    assert all(row["verdict"] == "" for row in rows)
