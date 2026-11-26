"""P3.2 championship pack: verify evidence boundaries and no invented awards."""
import copy

import pytest

from app.finals import finals_overview
from evals.p3_2_championship_pack import compile_pack, markdown

COMMIT = "793317bbde227b4a0cad50f712da3cb871a00d32"


def _overview(client):
    response = client.get("/competition/finals/overview?lang=zh")
    assert response.status_code == 200, response.text
    return response.json()


def test_pack_maps_all_11_official_criteria_and_fail_closed_claims(client):
    data = _overview(client)
    packet = compile_pack(data, COMMIT)
    assert packet["schema"] == "globalinfra.p3-2.championship-pack.v1"
    assert packet["status"] == "REHEARSAL_PACK_ONLY"
    assert packet["publication_gate"] == "CLOSED_PENDING_INDEPENDENT_SOURCE_AUDIT"
    assert len(packet["scorecard"]) == 11
    assert sum(x["max_score"] for x in packet["scorecard"]) == 100
    assert all(x["awarded_score"] is None for x in packet["scorecard"])
    assert packet["capabilities"]["MODEL_SUPERIORITY"] == "NOT_RUN"
    assert packet["capabilities"]["REAL_FIELD_ROI"] == "NO_AUDITED_PUBLIC_RESULT"
    assert packet["scenario"]["external_delivery"] == "NOT_SENT"
    assert len(packet["five_minute_script"]) == 6
    assert len(packet["jury_questions"]) >= 8
    rendered = markdown(packet)
    assert "NOT_RUN" in rendered
    assert "NO_AUDITED_PUBLIC_RESULT" in rendered


@pytest.mark.parametrize("key,value,reason", [
    ("scoring_standard", "FAKE_SCORECARD", "RUBRIC_ID_MISMATCH"),
    ("schema", "UNTRUSTED", "OVERVIEW_SCHEMA_MISMATCH"),
])
def test_pack_rejects_unapproved_data_contract(client, key, value, reason):
    data = _overview(client)
    data[key] = value
    with pytest.raises(ValueError, match=reason):
        compile_pack(data, COMMIT)


@pytest.mark.parametrize("path,value,reason", [
    (("scenario", "synthetic"), False, "REAL_CASE_NOT_PUBLICLY_CLEARED"),
    (("mission", "external_delivery_performed"), True, "EXTERNAL_DELIVERY_CLAIM_FORBIDDEN"),
    (("mission", "project_safety_case_closed"), True, "PHYSICAL_CLOSURE_CLAIM_FORBIDDEN"),
    (("business_impact", "model_comparison", "status"), "VERIFIED", "REAL_MODEL_RESULT_MUST_USE_SEPARATE_APPROVED_EVIDENCE"),
    (("business_impact", "paired_roi", "improvement_percent"), 50, "PUBLIC_ROI_CLAIM_MUST_HAVE_SEPARATE_APPROVED_EVIDENCE"),
    (("country_adaptation", "status"), "CERTIFIED", "COUNTRY_LAW_CERTIFICATION_NOT_ESTABLISHED"),
])
def test_pack_blocks_unsupported_business_assertions(client, path, value, reason):
    data = _overview(client)
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match=reason):
        compile_pack(data, COMMIT)


def test_release_requires_commit_bound_signed_evidence(client):
    data = _overview(client)
    packet = compile_pack(data, COMMIT)
    assert packet["release"]["signed_release_matches_commit"] is False or (
        packet["release"]["commit_prefix"] == COMMIT[:12]
        and data["release"]["status"] == "VERIFIED_PASSED"
    )
    fake = copy.deepcopy(data)
    fake["release"]["status"] = "VERIFIED_PASSED"
    fake["release"]["commit"] = "b" * 12
    result = compile_pack(fake, COMMIT)
    assert result["release"]["signed_release_matches_commit"] is False
    assert result["release"]["passed_cases"] is None
    fake["release"]["commit"] = COMMIT[:12]
    assert compile_pack(fake, COMMIT)["release"]["signed_release_matches_commit"] is True


def test_pack_fails_on_nonexact_revision_and_altered_rubric(client):
    data = _overview(client)
    with pytest.raises(ValueError, match="EXACT_FORTY_HEX_COMMIT_REQUIRED"):
        compile_pack(data, "main")
    data["scorecard"][0]["max_score"] = 11
    with pytest.raises(ValueError, match="OFFICIAL_SCORE_WEIGHTS_MISMATCH"):
        compile_pack(data, COMMIT)
