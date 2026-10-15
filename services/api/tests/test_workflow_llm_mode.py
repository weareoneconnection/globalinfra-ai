"""When a model is configured, each specialist's finding must be written by
that model from its own tool results, and a model claim that cites evidence
the agent did not retrieve must be downgraded instead of accepted. Exercised
with fake models so the test stays network-free while proving the wiring.
"""
import asyncio
import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.agent_org.coordination as coordination
import app.agent_org.findings as findings
import app.agent_org.team as team
import app.workflow as workflow
from app.database import Base
from app.models import AgentRun, AgentTrace
from app.seed import seed


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    seed(db)
    return db


def _live(monkeypatch, finding_for):
    monkeypatch.setattr(workflow.settings, "llm_mode", "live")
    monkeypatch.setattr(workflow.settings, "openai_compat_api_key", "test-key")
    seen = []

    async def fake_finding(system, user, response_format=None, route=None, sensitivity="internal"):
        seen.append(user)
        return json.dumps(finding_for(system, user))

    async def no_additions(*args, **kwargs):
        return json.dumps({"additions": []})

    async def no_issues(*args, **kwargs):
        return json.dumps({"issues": []})

    monkeypatch.setattr(findings, "generate", fake_finding)
    monkeypatch.setattr(team, "generate", no_additions)
    monkeypatch.setattr(coordination, "generate", no_issues)
    return seen


def test_specialist_findings_are_produced_by_the_configured_model(monkeypatch):
    db = _db()

    def finding_for(system, user):
        ref = "CTR-A / Clause C-14.2" if "Contract Agent" in system else ""
        return {
            "status": "SUPPORTED" if ref else "GAP",
            "claim_en": "Model-generated finding grounded in the retrieved evidence." if ref else "Model notes a gap.",
            "claim_zh": "模型生成的、基于检索证据的结论。" if ref else "模型记录了证据缺口。",
            "evidence_refs": [ref] if ref else [], "confidence": 0.9, "gaps": [],
            "actions": [{"text_en": "Reply citing the clause", "text_zh": "引用条款答复", "owner_en": "Contract Manager", "owner_zh": "合同经理"}],
            "question_en": "", "question_zh": "",
        }

    seen = _live(monkeypatch, finding_for)
    asyncio.run(workflow.analyze_case(db, "CASE-2026-0182"))

    runs = {r.agent["en"]: r.summary for r in db.scalars(select(AgentRun).where(AgentRun.case_id == "CASE-2026-0182"))}
    assert runs["Contract Agent"]["en"] == "Model-generated finding grounded in the retrieved evidence."
    assert runs["Contract Agent"]["zh"] == "模型生成的、基于检索证据的结论。"
    # The model was handed the agent's own tool results, not a generic prompt.
    assert any("CTR-A" in prompt for prompt in seen)
    trace = db.scalar(select(AgentTrace).where(AgentTrace.case_id == "CASE-2026-0182", AgentTrace.agent_id == "contract", AgentTrace.round == 1))
    assert trace.method == "llm" and trace.output["status"] == "SUPPORTED"


def test_model_claim_citing_unretrieved_evidence_is_downgraded(monkeypatch):
    db = _db()

    def finding_for(system, user):
        return {"status": "SUPPORTED", "claim_en": "Per FIDIC 13.3 the contractor is entitled.", "claim_zh": "依据 FIDIC 13.3 承包商有权。",
                "evidence_refs": ["FIDIC 13.3"], "confidence": 0.95, "gaps": [], "actions": [], "question_en": "", "question_zh": ""}

    _live(monkeypatch, finding_for)
    asyncio.run(workflow.analyze_case(db, "CASE-2026-0182"))
    trace = db.scalar(select(AgentTrace).where(AgentTrace.case_id == "CASE-2026-0182", AgentTrace.agent_id == "contract", AgentTrace.round == 1))
    assert trace.output["status"] == "GAP" and trace.output["downgraded"] is True
    assert trace.output["evidence_refs"] == []


def test_citation_matching_ignores_spacing_but_not_identity(monkeypatch):
    db = _db()

    def finding_for(system, user):
        return {"status": "SUPPORTED", "claim_en": "Responsibility follows the clause.", "claim_zh": "责任依条款划分。",
                "evidence_refs": ["ctr-a/clausec-14.2"], "confidence": 0.9, "gaps": [],
                "actions": [{"text_en": "Reply", "text_zh": "答复", "owner_en": "Contract Manager", "owner_zh": "合同经理"}],
                "question_en": "", "question_zh": ""}

    _live(monkeypatch, finding_for)
    asyncio.run(workflow.analyze_case(db, "CASE-2026-0182"))
    trace = db.scalar(select(AgentTrace).where(AgentTrace.case_id == "CASE-2026-0182", AgentTrace.agent_id == "contract", AgentTrace.round == 1))
    assert trace.output["status"] == "SUPPORTED" and trace.output["evidence_refs"] == ["CTR-A / Clause C-14.2"]


def test_failed_follow_up_never_falls_back_to_rules(monkeypatch):
    """When the model fails during round 2, the round-1 finding must stand."""
    db = _db()
    calls = {"n": 0}

    def finding_for(system, user):
        calls["n"] += 1
        if "Coordinator follow-up" in user:
            raise RuntimeError("model down")
        return {"status": "GAP", "claim_en": "Not enough evidence.", "claim_zh": "证据不足。", "evidence_refs": [], "confidence": 0.3,
                "gaps": [], "actions": [], "question_en": "", "question_zh": ""}

    seen = _live(monkeypatch, finding_for)

    async def flaky(system, user, response_format=None, route=None, sensitivity="internal"):
        seen.append(user)
        if "Coordinator follow-up" in user:
            from app.llm import LLMError
            raise LLMError("model down")
        return json.dumps(finding_for(system, user))

    monkeypatch.setattr(findings, "generate", flaky)
    asyncio.run(workflow.analyze_case(db, "CASE-2026-0182"))
    adopted = list(db.scalars(select(AgentTrace).where(AgentTrace.case_id == "CASE-2026-0182", AgentTrace.round == 2, AgentTrace.kind == "specialist")))
    assert adopted == []
    contract = db.scalar(select(AgentTrace).where(AgentTrace.case_id == "CASE-2026-0182", AgentTrace.agent_id == "contract", AgentTrace.round == 1))
    assert contract.output["status"] == "GAP"
