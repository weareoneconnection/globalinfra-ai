"""Integration tests pinning down that /cases/{id}/analyze is a real,
content-grounded multi-agent pipeline (see app/workflow.py) rather than a
script keyed off a specific case id: different cases must engage different
specialist agents (routed from Case.type), cite evidence that actually
exists in the knowledge base, and produce verification scores computed
from that evidence instead of fixed numbers.
"""

KNOWN_SOURCE_REFS = {
    "CTR-A / Clause C-14.2", "RM-03 / Rev C", "SI-028", "ENG-NOTE-017", "MY-HSE-WAH-01",
}


def _analyze(client, case_id):
    r = client.post(f"/cases/{case_id}/analyze")
    assert r.status_code == 200
    return client.get(f"/cases/{case_id}").json()


def test_contract_case_engages_contract_engineering_and_interface_agents(client):
    detail = _analyze(client, "CASE-2026-0182")
    agents = [r["agent"] for r in detail["agent_runs"]]
    assert "Contract Agent" in agents
    assert "Engineering Agent" in agents
    assert "Interface Agent" in agents
    # Routing is by case type, not a hardcoded id: an HSE-only agent should
    # not be pulled into a contract/technical-interface case.
    assert "HSE Agent" not in agents


def test_hse_case_engages_a_different_agent_set_than_the_contract_case(client):
    detail = _analyze(client, "CASE-2026-0194")
    agents = [r["agent"] for r in detail["agent_runs"]]
    assert "HSE Agent" in agents
    assert "Compliance Agent" in agents
    assert "Contract Agent" not in agents


def test_evidence_citations_resolve_to_real_knowledge_documents(client):
    detail = _analyze(client, "CASE-2026-0182")
    assert detail["evidence"], "expected at least one grounded citation"
    for item in detail["evidence"]:
        assert item["source_ref"] in KNOWN_SOURCE_REFS
        assert 0.0 < item["confidence"] <= 0.97


def test_verification_scores_are_derived_from_the_actual_run(client):
    detail = _analyze(client, "CASE-2026-0182")
    v = detail["verification"]
    assert v is not None
    for key in ("citation_score", "evidence_score", "consistency_score"):
        assert 0.0 <= v[key] <= 1.0
    # The flagship case's three engaged specialists (contract, engineering,
    # interface) all clear the confidence threshold against the seeded
    # knowledge base, so every finding should be cited and confident.
    assert v["citation_score"] == 1.0
    assert v["consistency_score"] == 1.0


def test_low_signal_case_is_flagged_as_an_evidence_gap_not_a_false_conclusion(client):
    # CASE-2026-0201 (Quality) has no quality-specific document in the
    # seeded knowledge base, so at least one engaged specialist must record
    # a gap instead of fabricating a confident finding.
    detail = _analyze(client, "CASE-2026-0201")
    v = detail["verification"]
    assert v["consistency_score"] < 1.0
    summaries = " ".join(r["summary"] for r in detail["agent_runs"])
    assert "gap" in summaries.lower()


def test_routed_case_cites_only_its_country_or_neutral_sources(client):
    text = "马来西亚项目 P47 墩高处作业无防护，工人未系安全带，要求 24 小时内整改。"
    case_id = client.post("/intake/text", json={"text": text, "project_id": 1}).json()["case_id"]
    refs = [e["source_ref"] for e in client.get(f"/cases/{case_id}").json()["evidence"]]
    assert refs and not any(ref.startswith(("AE-", "SA-", "ID-")) for ref in refs)
