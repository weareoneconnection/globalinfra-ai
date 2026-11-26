"""P3.1.1 synthetic-only review council regression tests.

These exercise validation and aggregation, NEVER actual expert expertise.
"""
import copy
import json
from pathlib import Path

import pytest

from evals.p3_1_hybrid_council import (
    SCHEMA, HUMAN, QUEUE, execute, human_gate, host_of, make_queue,
    normalize, sha, validate,
)
from evals.p3_1_study import BLIND_SCHEMA, STUDY_SCHEMA


def factory():
    cases = []
    for k in range(50):
        cases.append({
            "case_id": f"TEST-{k:03d}", "notice": f"SYNTHETIC case {k}",
            "evidence_context": [{"ref": f"REF-{k}", "text": "TEST ONLY"}],
            "candidates": [
                {"alias": alias, "risk": "CRITICAL" if k < 5 else "MEDIUM",
                 "action": "REQUEST HUMAN REVIEW", "evidence_refs": [f"REF-{k}"],
                 "abstained": False}
                for alias in "ABCD"
            ],
        })
    study = {
        "schema": STUDY_SCHEMA, "publication_gate": "CLOSED",
        "protocol_id": "TEST-COUNCIL-001",
        "dataset": {"sha256": "a" * 64, "cases": 50,
                    "source_classification": "PUBLIC_ONLY"},
        "execution": {"model_id": "evaluated-model"},
    }
    packet = {
        "schema": BLIND_SCHEMA, "dataset_sha256": "a" * 64,
        "comparison_sha256": "b" * 64, "cases": cases,
    }
    key = {"packet_sha256": sha(packet), "comparison_sha256": "b" * 64}
    def expert(id, family, specialty):
        return {"id": id, "role": "expert", "family": family,
                "specialty": specialty, "model": id + "-model",
                "endpoint": f"https://{id}.example.test/v1/chat/completions",
                "api_key_env": "COUNCIL_" + id.upper().replace("-", "_") + "_API_KEY"}
    experts = [expert("expert-alpha", "family-alpha", "hse"),
               expert("expert-beta", "family-beta", "engineering"),
               expert("expert-gamma", "family-gamma", "contracts")]
    arbiter = expert("arbiter-delta", "family-delta", "contracts")
    arbiter["role"] = "arbiter"
    registry = {
        "schema": SCHEMA, "mode": "AI_SCREENING_ONLY",
        "experts": experts, "arbiter": arbiter,
        "evaluated_model_ids": ["raw-model", "rag-model", "governed-model"],
        "human_gate_required": True,
    }
    hosts = {f"{x['id']}.example.test" for x in experts + [arbiter]}
    return study, packet, key, registry, hosts


def model_answer(prompt):
    payload = json.loads(prompt[1]["content"])
    return {
        "risk": "CRITICAL" if "case 0" in payload["notice"] else "MEDIUM",
        "requires_abstention": False,
        "candidates": [{
            "alias": x["alias"], "action_appropriate": True,
            "citation_supported": True, "abstention_appropriate": True,
            "unsafe_recommendation": False,
            "supporting_refs": [payload["references"][0]["ref"]],
        } for x in payload["blinded_candidates"]],
    }


def test_three_family_live_simulation_is_ai_only_and_has_human_gate():
    study, packet, key, config, hosts = factory()
    calls = []
    def fake(member, prompt):
        calls.append(member["id"])
        return model_answer(prompt)
    result = execute(study, packet, key, config, fake,
                     allowed_hosts=hosts, authorized=True, max_calls=600)
    assert result["status"] == "AI_ONLY_REVIEW_COMPLETED"
    assert result["publication_gate"] == "CLOSED"
    assert result["calls"] >= 300
    assert all(len(x["ai_reviews"]) == 3 for x in result["records"])
    assert all(x["ai_arbiter"] is None for x in result["records"])
    queue = make_queue(packet, result)
    assert queue["schema"] == QUEUE
    assert queue["mandatory_cases"] >= 5
    assert queue["publication_gate"] == "CLOSED"
    assert all(x["minimum_distinct_human_reviewers"] == 2
               for x in queue["tasks"] if "CRITICAL" in x["reasons"])
    incomplete = human_gate(queue, result, [])
    assert incomplete["status"] == "HUMAN_REVIEW_INCOMPLETE"
    assert incomplete["publication_gate"].startswith("CLOSED_")


def test_reviewer_and_arbitration_disagreement():
    study, packet, key, config, hosts = factory()
    def fake(member, prompt):
        result = model_answer(prompt)
        if member["id"] == "expert-beta":
            result["candidates"][0]["unsafe_recommendation"] = True
        return result
    report = execute(study, packet, key, config, fake,
                     allowed_hosts=hosts, authorized=True, max_calls=450)
    assert report["calls"] == 350
    assert all("CROSS_MODEL_DISAGREEMENT" in r["flags"] for r in report["records"])
    assert all(r["ai_arbiter"]["scope"] == "AI_ONLY_NOT_HUMAN_ADJUDICATION"
               for r in report["records"])


def test_registry_rejects_self_grading_same_family_and_unapproved_endpoint():
    study, packet, key, registry, hosts = factory()
    bad = copy.deepcopy(registry)
    bad["experts"][1]["family"] = "family-alpha"
    with pytest.raises(ValueError, match="THREE_DISTINCT_MODEL_FAMILIES_REQUIRED"):
        validate(bad, study, packet, key, hosts)
    bad = copy.deepcopy(registry)
    bad["experts"][0]["model"] = "governed-model"
    with pytest.raises(ValueError, match="SELF_EVALUATION_MODEL_FORBIDDEN"):
        validate(bad, study, packet, key, hosts)
    bad = copy.deepcopy(registry)
    bad["experts"][0]["endpoint"] = "https://not-authorized.test/v1/chat/completions"
    with pytest.raises(ValueError, match="ENDPOINT_NOT_ALLOWLISTED"):
        validate(bad, study, packet, key, hosts)
    bad = copy.deepcopy(registry)
    bad["human_gate_required"] = False
    with pytest.raises(ValueError, match="HUMAN_GATE_REQUIRED"):
        validate(bad, study, packet, key, hosts)
    with pytest.raises(ValueError, match="HTTPS_REQUIRED"):
        host_of("http://public.example.com/v1/chat/completions")
    with pytest.raises(ValueError, match="PUBLIC_DNS_HOST_REQUIRED"):
        host_of("https://10.1.2.3/v1/chat/completions")


def test_citation_ids_must_exist_and_unknown_ref_forces_human_review():
    study, packet, key, registry, hosts = factory()
    reply = model_answer([{}, {"content": json.dumps({
        "notice": "case 1", "references": packet["cases"][0]["evidence_context"],
        "blinded_candidates": packet["cases"][0]["candidates"],
    })}])
    reply["candidates"][0]["supporting_refs"] = ["UNKNOWN"]
    first = normalize(reply, packet["cases"][0])
    assert first["candidates"]["A"]["citation_supported"] is False
    assert first["candidates"]["A"]["citation_anomaly"] is True
    with pytest.raises(ValueError, match="JUDGE_BOOLEAN_FIELDS_REQUIRED"):
        broken = copy.deepcopy(reply)
        broken["candidates"][0]["action_appropriate"] = "true"
        normalize(broken, packet["cases"][0])


def test_human_gate_records_are_not_cryptographic_signatures():
    study, packet, key, registry, hosts = factory()
    def fake(member, prompt):
        return model_answer(prompt)
    report = execute(study, packet, key, registry, fake,
                     allowed_hosts=hosts, authorized=True, max_calls=400)
    queue = make_queue(packet, report)
    queue_hash = sha(queue)
    records = []
    for task in queue["tasks"]:
        for idx in range(task["minimum_distinct_human_reviewers"]):
            records.append({
                "case_id": task["case_id"], "role": "reviewer",
                "reviewer_id": f"reviewer-{idx}",
                "decision": "ACCEPT",
                "signed_review_ref": f"unverified-human-claim-{idx}",
                "queue_sha256": queue_hash,
            })
    closed = human_gate(queue, report, records)
    assert closed["schema"] == HUMAN
    assert closed["status"] == "HUMAN_REVIEW_RECORDS_COMPLETE_SOURCE_AUDIT_PENDING"
    assert closed["identity_and_signatures_cryptographically_verified"] is False
    assert closed["publication_gate"].startswith("CLOSED_")
    wrong = copy.deepcopy(records)
    wrong[0]["queue_sha256"] = "bad"
    with pytest.raises(ValueError, match="HUMAN_REVIEW_PROVENANCE_INVALID"):
        human_gate(queue, report, wrong)


def test_not_run_default_does_not_call_models():
    from evals.p3_1_hybrid_council import main
    import sys
    old = sys.argv
    sys.argv = ["p3_1_hybrid_council.py", "run", "--study", "missing",
                "--packet", "missing", "--blind-key", "missing",
                "--registry", "missing", "--output", "/tmp/council-not-run-test.json"]
    try:
        assert main() == 0
    finally:
        sys.argv = old
    assert json.loads(Path("/tmp/council-not-run-test.json").read_text())["status"] == "NOT_RUN"
    Path("/tmp/council-not-run-test.json").unlink()
