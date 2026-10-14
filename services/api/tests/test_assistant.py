"""Tests for the conversational assistant router (``/assistant/chat``).

Mock mode (the default) exercises the deterministic planner. Real-model tests
monkeypatch ``app.assistant.generate`` and the shared ``settings`` singleton,
so no network call is ever made.
"""
import json

import pytest

from app.assistant import TOOLS, PLAN_FORMAT, _parse_plan, _validate_answer, plan_rules
from app.config import settings

PROJECTS = {"MY-RAIL-A": 1, "ID-HWY-B": 2}


def _real_mode(monkeypatch, fake_generate):
    monkeypatch.setattr(settings, "llm_mode", "openai")
    monkeypatch.setattr(settings, "openai_compat_api_key", "test-key")
    monkeypatch.setattr("app.assistant.generate", fake_generate)


def _plan_json(**fields):
    base = {"tool": "answer_directly", "query": "", "case_id": "", "project_code": "", "reply": ""}
    base.update(fields)
    return json.dumps(base)


# --- deterministic planner ----------------------------------------------------

@pytest.mark.parametrize("message, tool", [
    ("你能做什么？", "answer_directly"),
    ("hello", "answer_directly"),
    ("马来西亚高处作业有什么要求？", "search_knowledge"),
    ("业主通知：P47 墩高处作业无防护，要求48小时内整改", "report_incident"),
    ("你好，P47墩发生坍塌事故，有人受伤", "report_incident"),
    ("待我审批", "pending_approvals"),
    ("项目进展", "project_progress"),
])
def test_rules_planner(message, tool):
    assert plan_rules(message, PROJECTS, set())["tool"] == tool


def test_rules_planner_resolves_project_code_and_known_case():
    plan = plan_rules("MY-RAIL-A 项目进展", PROJECTS, set())
    assert plan["tool"] == "project_progress" and plan["project_id"] == 1
    assert plan_rules("CASE-ABC123 现在到哪一步了", PROJECTS, {"CASE-ABC123"})["case_id"] == "CASE-ABC123"
    # An unknown case id is never trusted.
    assert plan_rules("CASE-NOPE 现在到哪一步了", PROJECTS, set())["tool"] != "case_status"


# --- model plan validation ----------------------------------------------------

def test_plan_schema_enum_tracks_tools():
    assert PLAN_FORMAT["json_schema"]["schema"]["properties"]["tool"]["enum"] == list(TOOLS)


def test_parse_plan_rejects_unknown_tool_project_and_case():
    assert _parse_plan(_plan_json(tool="approve_everything"), PROJECTS, set()) is None
    assert _parse_plan(_plan_json(tool="project_progress", project_code="XX-NONE"), PROJECTS, set()) is None
    assert _parse_plan(_plan_json(tool="case_status", case_id="CASE-GHOST"), PROJECTS, set()) is None
    assert _parse_plan(_plan_json(tool="answer_directly", reply=""), PROJECTS, set()) is None
    assert _parse_plan("not json", PROJECTS, set()) is None


def test_parse_plan_accepts_valid_plan_with_prose_around_it():
    raw = "Sure:\n```json\n" + _plan_json(tool="case_status", case_id="case-abc123") + "\n```"
    plan = _parse_plan(raw, PROJECTS, {"CASE-ABC123"})
    assert plan["tool"] == "case_status" and plan["case_id"] == "CASE-ABC123"


def test_answer_must_cite_only_retrieved_sources():
    refs = {"MY-HSE-WAH-01", "MY-DOSH-OSHA"}
    assert _validate_answer("Use guardrails [MY-HSE-WAH-01].", refs)
    assert not _validate_answer("Use guardrails.", refs)
    assert not _validate_answer("Use guardrails [MY-HSE-WAH-01] per [OSHA-1910].", refs)


# --- endpoint: offline ----------------------------------------------------------

def test_chat_offline_uses_rules(client):
    body = client.post("/assistant/chat", json={"message": "你能做什么？"}).json()
    assert body["tool"] == "answer_directly" and body["method"] == "rules" and body["reply"] is None


def test_chat_offline_knowledge_returns_only_confident_sources(client):
    body = client.post("/assistant/chat?lang=zh", json={"message": "马来西亚高处作业有什么要求？"}).json()
    assert body["tool"] == "search_knowledge" and body["answer_method"] == "sources"
    assert body["hits"] and all(hit["relevance"] >= 0.22 for hit in body["hits"])
    assert body["hits"][0]["source_ref"] == "MY-HSE-WAH-01"


def test_chat_offline_off_topic_question_declines(client):
    body = client.post("/assistant/chat", json={"message": "明天吉隆坡天气怎么样？"}).json()
    assert body["tool"] == "search_knowledge" and body["hits"] == [] and body["reply"] is None


# --- endpoint: with a model -------------------------------------------------------

def test_chat_llm_direct_reply(client, monkeypatch):
    async def fake(system, user, response_format=None, route=None, sensitivity="internal"):
        return _plan_json(reply="我可以帮你上报事件、查法规、看进展和处理审批。")
    _real_mode(monkeypatch, fake)
    body = client.post("/assistant/chat", json={"message": "你都会些啥"}).json()
    assert body["method"] == "llm" and body["tool"] == "answer_directly"
    assert body["reply"].startswith("我可以")


def test_chat_llm_resolves_case_from_history(client, monkeypatch):
    case_id = client.post("/intake/text", json={"text": "Owner notice: access road damage, rectify within 48 hours.", "project_id": 1}).json()["case_id"]

    async def fake(system, user, response_format=None, route=None, sensitivity="internal"):
        assert case_id in user  # the conversation is passed to the planner
        return _plan_json(tool="case_status", case_id=case_id)
    _real_mode(monkeypatch, fake)
    body = client.post("/assistant/chat", json={
        "message": "那个工单现在到哪一步了？",
        "history": [{"role": "user", "content": "access road damage"},
                    {"role": "assistant", "content": f"Created work order {case_id}"}],
    }).json()
    assert body["method"] == "llm" and body["tool"] == "case_status" and body["case_id"] == case_id


def test_chat_llm_grounded_knowledge_answer(client, monkeypatch):
    calls = []

    async def fake(system, user, response_format=None, route=None, sensitivity="internal"):
        calls.append(response_format)
        if response_format is not None:
            return _plan_json(tool="search_knowledge", query="Malaysia working at height")
        return "Provide edge protection and permits [MY-HSE-WAH-01]."
    _real_mode(monkeypatch, fake)
    body = client.post("/assistant/chat", json={"message": "What applies to working at height in Malaysia?"}).json()
    assert body["tool"] == "search_knowledge" and body["answer_method"] == "llm"
    assert "[MY-HSE-WAH-01]" in body["reply"] and len(calls) == 2


def test_chat_llm_uncited_answer_is_discarded(client, monkeypatch):
    async def fake(system, user, response_format=None, route=None, sensitivity="internal"):
        if response_format is not None:
            return _plan_json(tool="search_knowledge", query="Malaysia working at height")
        return "Always wear a harness above 2 metres."  # no citation -> not trusted
    _real_mode(monkeypatch, fake)
    body = client.post("/assistant/chat", json={"message": "What applies to working at height in Malaysia?"}).json()
    assert body["answer_method"] == "sources" and body["reply"] is None and body["hits"]


def test_chat_llm_invalid_plan_falls_back_to_rules(client, monkeypatch):
    async def fake(system, user, response_format=None, route=None, sensitivity="internal"):
        return _plan_json(tool="approve_everything")
    _real_mode(monkeypatch, fake)
    body = client.post("/assistant/chat", json={"message": "待我审批"}).json()
    assert body["method"] == "rules" and body["tool"] == "pending_approvals"


def test_chat_llm_cannot_brush_off_an_incident(client, monkeypatch):
    async def fake(system, user, response_format=None, route=None, sensitivity="internal"):
        return _plan_json(reply="Sounds bad, take care!")
    _real_mode(monkeypatch, fake)
    body = client.post("/assistant/chat", json={"message": "Bridge pier damage reported by the owner, rectify in 24 hours."}).json()
    assert body["tool"] == "report_incident"


def test_chat_restricted_never_reaches_cloud_model(client, monkeypatch):
    async def fake(*args, **kwargs):
        raise AssertionError("cloud model must not be called for restricted data")
    monkeypatch.setattr(settings, "llm_mode", "openai")
    monkeypatch.setattr(settings, "openai_compat_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_preferred_provider", "openai")
    monkeypatch.setattr(settings, "local_llm_base_url", "")
    monkeypatch.setattr("app.assistant.generate", fake)
    body = client.post("/assistant/chat", json={"message": "待我审批", "data_classification": "restricted", "model_route": "openai"})
    assert body.status_code == 200 and body.json()["method"] == "rules"


def test_chat_explicit_tool_skips_planning(client, monkeypatch):
    async def fake(system, user, response_format=None, route=None, sensitivity="internal"):
        assert response_format is None, "planner must not run when the user picked the tool"
        return "Edge protection is required [MY-HSE-WAH-01]."
    _real_mode(monkeypatch, fake)
    body = client.post("/assistant/chat", json={"message": "马来西亚 高处作业", "tool": "search_knowledge"}).json()
    assert body["method"] == "user" and body["tool"] == "search_knowledge" and body["answer_method"] == "llm"


def test_chat_rewritten_query_cannot_lose_hits_found_by_original_words(client, monkeypatch):
    async def fake(system, user, response_format=None, route=None, sensitivity="internal"):
        if response_format is not None:
            return _plan_json(tool="search_knowledge", query="zzz unrelated wording")
        return "[MY-HSE-WAH-01] applies."
    _real_mode(monkeypatch, fake)
    body = client.post("/assistant/chat", json={"message": "马来西亚高处作业有什么要求？"}).json()
    assert "MY-HSE-WAH-01" in [hit["source_ref"] for hit in body["hits"]]
