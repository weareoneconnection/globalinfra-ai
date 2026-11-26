"""P1 finals evidence contracts: no fabricated model, ROI or country claims."""
import json
from pathlib import Path

import pytest

from evals.run_country_adaptation import report as country_report
from evals.run_model_comparison import (
    grade, is_approved_endpoint, normalized_prediction, validate_dataset,
)


def test_country_adaptation_exposes_real_configuration_differences_only():
    payload = country_report("MY", "AE", "construction")
    assert payload["status"] == "CONFIGURATION_COMPARISON_ONLY"
    assert payload["differences"]["languages_changed"] is True
    assert payload["differences"]["authorities_changed"] is True
    assert payload["first"]["review_gate"] == "EXPERT_REVIEW_REQUIRED"
    assert payload["second"]["status"] == "DEMO_CONFIG_ONLY"
    assert len(payload["config_sha256"]["MY"]) == 64
    assert len(payload["config_sha256"]["AE"]) == 64
    assert payload["first"]["source_indexes"]
    assert "not a verified legal analysis" in payload["boundary"]


def test_country_adaptation_rejects_same_or_unknown_codes():
    with pytest.raises(ValueError, match="COUNTRIES_MUST_DIFFER"):
        country_report("MY", "MY")
    with pytest.raises(ValueError, match="UNKNOWN_COUNTRY_PACK"):
        country_report("MY", "ZZ")


def test_blinded_model_dataset_requires_minimum_and_unique_ids(tmp_path):
    path = tmp_path / "blind.jsonl"
    row = {
        "id": "CASE-001", "input": "working at height with unprotected edge",
        "expected_risk": "CRITICAL", "expected_action": "STOP_WORK",
        "expected_evidence": ["DOC-001"], "requires_abstention": False,
        "data_classification": "public",
        "evidence_context": [{"ref": "DOC-001", "text": "approved policy excerpt"}],
    }
    path.write_text(json.dumps(row) + "\n")
    rows, reasons, checksum = validate_dataset(path)
    assert len(rows) == 1 and len(checksum) == 64
    assert "BLINDED_DATASET_BELOW_MINIMUM_50" in reasons
    path.write_text("\n".join(json.dumps(row) for _ in range(50)) + "\n")
    _, reasons, _ = validate_dataset(path)
    assert "DUPLICATE_OR_INVALID_CASE_IDS" in reasons


def test_model_prediction_grading_does_not_fabricate_cost_or_claims():
    rows = [
        {"id": "C1", "expected_risk": "CRITICAL",
         "expected_evidence": ["DOC-1"], "requires_abstention": False},
        {"id": "C2", "expected_risk": "LOW",
         "expected_evidence": [], "requires_abstention": True},
    ]
    first = normalized_prediction(
        "C1", {"risk": "CRITICAL", "action": "STOP_WORK",
               "evidence_refs": ["DOC-1"], "abstained": False}, 180, "rag")
    second = normalized_prediction(
        "C2", {"risk": "LOW", "action": "REQUEST_MORE_EVIDENCE",
               "evidence_refs": [], "abstained": True}, 300, "rag")
    result = grade(rows, [first, second])
    assert result["critical_risk_recall"] == 1.0
    assert result["citation_precision"] == 1.0
    assert result["correct_abstention_rate"] == 1.0
    assert result["cost_per_case"] is None
    assert result["unauthorized_execution_count"] == 0
    with pytest.raises(ValueError, match="PREDICTION_SET_INCOMPLETE"):
        grade(rows, [first])


def test_model_endpoint_guard_rejects_plaintext_cloud_and_credentials():
    assert not is_approved_endpoint("http://example.com/v1", False)
    assert not is_approved_endpoint("https://user:pass@example.com/v1", False)
    assert not is_approved_endpoint("http://127.0.0.1:9999/v1", False)
    assert is_approved_endpoint("http://127.0.0.1:9999/v1", True)
    assert is_approved_endpoint("https://model.example.test/v1", False)


def test_prediction_rejects_invalid_boolean_or_risk():
    with pytest.raises(ValueError, match="INVALID_PREDICTION_RISK"):
        normalized_prediction("C1", {
            "risk": "UNKNOWN", "action": "N/A", "evidence_refs": [],
            "abstained": False,
        }, 1.0, "raw_llm")
    with pytest.raises(ValueError, match="INVALID_PREDICTION_BOOLEAN"):
        normalized_prediction("C1", {
            "risk": "LOW", "action": "N/A", "evidence_refs": [],
            "abstained": "false",
        }, 1.0, "raw_llm")
