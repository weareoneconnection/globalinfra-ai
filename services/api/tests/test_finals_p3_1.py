"""P3.1 study pipeline tests. All fixtures are synthetic TEST_ONLY.

No result from these fixtures may be published as a real model or pilot score.
"""
import json

import pytest

from evals.p3_1_study import (
    adjudicate, blind_packet, canonical, digest, freeze, paired_effect,
    roster_roles, wilson, write_json,
)
from evals.run_model_comparison import GROUPS, normalized_prediction


def study_fixture(tmp_path):
    path = tmp_path / "authorized-public-fixture.TEST_ONLY.jsonl"
    rows = []
    for index in range(50):
        risk = "CRITICAL" if index < 10 else ("HIGH" if index < 25 else "MEDIUM")
        row = {
            "id": f"TEST-{index:03d}",
            "input": f"Synthetic TEST_ONLY notice case {index} - project query token {index * 5 + 17}",
            "expected_risk": risk,
            "expected_action": "REQUEST_HUMAN_REVIEW",
            "expected_evidence": [f"DOC-{index:03d}"],
            "requires_abstention": index >= 40,
            "data_classification": "public",
            "language": "en" if index % 2 else "ms",
            "evidence_context": [{
                "ref": f"DOC-{index:03d}",
                "text": f"TEST_ONLY synthetic project reference {index}",
            }],
        }
        rows.append(row)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    frozen = freeze(
        path, protocol_id="TEST-ONLY-P3-001",
        authorization_ref="TEST_ONLY_NOT_AUTHORIZED_REAL",
        attested_by="synthetic_test_runner", model_id="synthetic-model-only",
        provider_host="provider.example.test",
        governed_host="governed.example.test",
        source_commit="a" * 40,
    )
    raw_dir = tmp_path / "private_raw"
    raw_dir.mkdir()
    hash_by_arm = {}
    for arm in GROUPS:
        predictions = []
        for row in rows:
            pred = normalized_prediction(row["id"], {
                "risk": row["expected_risk"] if arm == "governed" else "MEDIUM",
                "action": "HUMAN_REVIEW_REQUIRED",
                "evidence_refs": row["expected_evidence"] if arm in ("governed", "rag") else [],
                "abstained": row["requires_abstention"],
                "external_action_executed": False,
            }, 10.0, arm)
            predictions.append(pred)
        target = raw_dir / f"{arm}.json"
        target.write_text(json.dumps(predictions, indent=2) + "\n", encoding="utf-8")
        hash_by_arm[arm] = digest(target.read_bytes())
    comparison = tmp_path / "comparison.TEST_ONLY.json"
    write_json(comparison, {
        "schema": "globalinfra.model-comparison.v2",
        "status": "EXECUTED_UNREVIEWED",
        "frozen_study_sha256": digest(canonical(frozen)),
        "dataset": {"sha256": frozen["dataset"]["sha256"]},
        "groups": [{"id": arm, "status": "EXECUTED_UNREVIEWED"} for arm in GROUPS],
        "raw_output_sha256": hash_by_arm,
    })
    packet, key = blind_packet(frozen, path, comparison, raw_dir)
    roster = {
        "schema": "globalinfra.p3-1.roster.v1",
        "independence_attested": True,  # test fixture, NOT real independence
        "reviewers": [
            {"id": "reviewer-a", "role": "reviewer", "specialty": "hse"},
            {"id": "reviewer-b", "role": "reviewer", "specialty": "engineering"},
            {"id": "reviewer-c", "role": "adjudicator", "specialty": "contracts"},
        ],
    }
    reviews = []
    for row in rows:
        for reviewer in ("reviewer-a", "reviewer-b"):
            reviews.append({
                "kind": "gold", "case_id": row["id"], "reviewer_id": reviewer,
                "risk": row["expected_risk"],
                "requires_abstention": row["requires_abstention"],
            })
        for alias in "ABCD":
            for reviewer in ("reviewer-a", "reviewer-b"):
                reviews.append({
                    "kind": "prediction", "case_id": row["id"], "alias": alias,
                    "reviewer_id": reviewer,
                    "action_appropriate": True,
                    "citation_supported": True,
                    "abstention_appropriate": True,
                    "unsafe_recommendation": False,
                })
    return frozen, path, comparison, raw_dir, packet, key, roster, reviews


def test_freeze_requires_minimum_50_distinct_and_diverse_cases(tmp_path):
    frozen, dataset, *_ = study_fixture(tmp_path)
    assert frozen["dataset"]["cases"] == 50
    assert frozen["dataset"]["critical_cases"] == 10
    assert frozen["dataset"]["abstention_cases"] == 10
    assert frozen["publication_gate"] == "CLOSED"
    dataset.write_text(dataset.read_text() + "\n")
    from evals.p3_1_study import validate_freeze
    with pytest.raises(ValueError, match="DATASET_CHANGED_AFTER_FREEZE"):
        validate_freeze(frozen, dataset)


def test_blinded_packet_protects_mapping_and_report_never_awards_claim(tmp_path):
    frozen, dataset, comp, raw, packet, key, roster, reviews = study_fixture(tmp_path)
    assert packet["schema"] == "globalinfra.p3-1.blind.v1"
    assert key["schema"] == "globalinfra.p3-1.blind-key.v1"
    assert all(set(k) == set("ABCD") for k in key["aliases"].values())
    assert "governed" not in json.dumps(packet)
    report = adjudicate(frozen, dataset, comp, raw, packet, key, roster, reviews)
    assert report["status"] == "EXPERT_ADJUDICATED_SOURCE_AUDIT_PENDING"
    assert report["publication_gate"] == "CLOSED_PENDING_SOURCE_AUDIT_AND_APPROVAL"
    assert report["review"]["expert_gold_reviewed"] == 50
    assert report["review"]["expert_candidate_reviews"] == 200
    assert report["arms"][3]["metrics"]["risk_accuracy"] == 1.0
    assert report["arms"][3]["metrics"]["cost_per_case"] is None
    assert report["paired_comparisons"]["governed_vs_rules"]["delta_risk_accuracy"] >= 0
    assert "TEST-000" not in json.dumps(report)
    assert "synthetic project reference" not in json.dumps(report)


def test_review_missing_disagreement_and_separate_adjudicator(tmp_path):
    frozen, dataset, comp, raw, packet, key, roster, reviews = study_fixture(tmp_path)
    incomplete = adjudicate(frozen, dataset, comp, raw, packet, key, roster, reviews[:-1])
    assert incomplete["status"] == "REVIEW_INCOMPLETE_OR_CONFLICTED"
    assert incomplete["arms"] == []
    changed = [dict(x) for x in reviews]
    for item in changed:
        if item["kind"] == "prediction" and item["case_id"] == "TEST-000" and item["alias"] == "A" and item["reviewer_id"] == "reviewer-b":
            item["action_appropriate"] = False
    disputed = adjudicate(frozen, dataset, comp, raw, packet, key, roster, changed)
    assert disputed["status"] == "REVIEW_INCOMPLETE_OR_CONFLICTED"
    assert any("ADJUDICATION_REQUIRED" in v for v in disputed["review"]["issues"])
    changed.append({
        "kind": "prediction", "case_id": "TEST-000", "alias": "A",
        "reviewer_id": "reviewer-c",
        "action_appropriate": False, "citation_supported": True,
        "abstention_appropriate": True, "unsafe_recommendation": False,
    })
    resolved = adjudicate(frozen, dataset, comp, raw, packet, key, roster, changed)
    assert resolved["status"] == "EXPERT_ADJUDICATED_SOURCE_AUDIT_PENDING"
    tampered = dict(packet)
    tampered["review_instructions"] = "test mutation"
    with pytest.raises(ValueError, match="BLIND_PACKET_TAMPERED"):
        adjudicate(frozen, dataset, comp, raw, tampered, key, roster, reviews)


def test_raw_prediction_digest_tampering_refused(tmp_path):
    frozen, dataset, comp, raw, packet, key, roster, reviews = study_fixture(tmp_path)
    path = raw / "raw_llm.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="RAW_OUTPUT_DIGEST_MISMATCH"):
        adjudicate(frozen, dataset, comp, raw, packet, key, roster, reviews)


def test_reviewer_role_and_statistics_gates(tmp_path):
    _, _, _, _, _, _, roster, _ = study_fixture(tmp_path)
    assert len(roster_roles(roster)[0]) == 2
    bad = dict(roster)
    bad["independence_attested"] = False
    with pytest.raises(ValueError, match="REVIEWER_INDEPENDENCE_NOT_ATTESTED"):
        roster_roles(bad)
    assert wilson(0, 0) is None
    assert wilson(5, 10)[0] < .5 < wilson(5, 10)[1]
    rows = [
        {"id": "TEST-0", "expected_risk": "CRITICAL"},
        {"id": "TEST-1", "expected_risk": "HIGH"},
        {"id": "TEST-2", "expected_risk": "LOW"},
    ]
    a = {"TEST-0": {"risk": "CRITICAL"}, "TEST-1": {"risk": "HIGH"}, "TEST-2": {"risk": "LOW"}}
    b = {"TEST-0": {"risk": "HIGH"}, "TEST-1": {"risk": "LOW"}, "TEST-2": {"risk": "LOW"}}
    diff = paired_effect(rows, a, b, "a" * 64)
    assert diff["paired_wins"] == 2
    assert diff["paired_losses"] == 0
    assert diff["delta_risk_accuracy"] == pytest.approx(2/3, abs=0.0001)
    assert 0 <= diff["exact_sign_test_two_sided_p"] <= 1
