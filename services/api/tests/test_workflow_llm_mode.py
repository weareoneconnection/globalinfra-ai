"""When a real OpenAI-compatible model is configured (llm_mode != mock and
an API key present), each specialist agent's finding must actually be
produced by that model (grounded in the retrieved evidence) and translated
through it -- not by the offline template path. This is exercised directly
against app.workflow with a fake model so the test stays network-free
while still proving the wiring (not just the offline fallback) works.
"""
import asyncio

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.workflow as workflow
from app.database import Base
from app.models import AgentRun
from app.seed import seed


def test_specialist_findings_are_produced_by_the_configured_model(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    seed(db)

    monkeypatch.setattr(workflow.settings, "llm_mode", "live")
    monkeypatch.setattr(workflow.settings, "openai_compat_api_key", "test-key")

    seen_prompts = []

    async def fake_generate(system, user):
        seen_prompts.append(user)
        return "Model-generated finding grounded in the retrieved evidence."

    async def fake_translate(text, target_lang, source_lang="en"):
        return "模型生成的、基于检索证据的结论。"

    monkeypatch.setattr(workflow, "generate", fake_generate)
    monkeypatch.setattr(workflow, "translate", fake_translate)

    asyncio.run(workflow.analyze_case(db, "CASE-2026-0182"))

    runs = {r.agent["en"]: r.summary for r in db.scalars(
        select(AgentRun).where(AgentRun.case_id == "CASE-2026-0182"))}

    assert runs["Contract Agent"]["en"] == "Model-generated finding grounded in the retrieved evidence."
    assert runs["Contract Agent"]["zh"] == "模型生成的、基于检索证据的结论。"
    # The model must have actually been handed the retrieved evidence, not
    # an empty/generic prompt.
    assert any("CTR-A" in p for p in seen_prompts)
