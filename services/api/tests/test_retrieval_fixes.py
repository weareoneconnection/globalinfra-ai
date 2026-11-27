"""Retrieval, routing and contract-review fixes found before the finals."""
import json
from types import SimpleNamespace

from app.assistant import _take_with_clause_slots, core_query
from app.contract_review import review
from app.country_knowledge import _expansion_glossary
from app.multilingual import expand_chinese
from app.retrieval import document_text


def _dispatch(client, message):
    response = client.post("/assistant/dispatch?lang=zh", json={"message": message})
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def _plan(events):
    return [s["agent"] for s in next(e for e in events if e["type"] == "plan")["steps"]]


def _refs(events):
    return [ref for e in events if e["type"] == "step_done" for ref in (e.get("refs") or [])] or [
        h["source_ref"] for e in events if e["type"] == "step_done" for h in (e.get("data") or {}).get("hits", [])]


def test_hyphenated_terms_survive_filler_removal():
    assert core_query("Compare UAE and Saudi end-of-service gratuity") == "end-of-service gratuity"
    assert core_query("what is the undang-undang on wages") == "wages"


def test_topic_tags_are_indexed_but_status_tags_are_not():
    doc = SimpleNamespace(title="t", category=None, jurisdiction=None, content="c", summary=None, source_ref="X",
                          tags=["foreign worker", "EXPERT_REVIEW_REQUIRED"])
    text = document_text(doc)
    assert "foreign worker" in text and "EXPERT_REVIEW_REQUIRED" not in text


def test_chinese_questions_gain_english_glossary_terms():
    glossary = _expansion_glossary(None)
    expanded, matches = expand_chinese("外籍工人工作准证怎么申请", glossary)
    assert "foreign worker" in expanded and "work permit" in expanded
    assert expand_chinese("明天天气怎么样", glossary) == ("明天天气怎么样", [])
    assert expand_chinese("foreign worker", glossary) == ("foreign worker", [])


def test_clauses_keep_half_the_slots():
    def doc(kind):
        return SimpleNamespace(document_type="CLAUSE_SUMMARY" if kind == "clause" else "SOP")
    kept = [(0.9, doc("source")), (0.8, doc("source")), (0.7, doc("source")), (0.6, doc("source")),
            (0.5, doc("clause")), (0.4, doc("clause")), (0.3, doc("clause")), (0.2, doc("clause"))]
    picked = _take_with_clause_slots(kept, 5)
    assert len(picked) == 5 and sum(d.document_type == "CLAUSE_SUMMARY" for _, d in picked) == 3
    assert [s for s, _ in picked] == sorted((s for s, _ in picked), reverse=True)


def test_english_legal_term_with_country_is_a_lookup(client):
    events = _dispatch(client, "Saudi Arabia liquidated damages for delay in construction contracts")
    assert _plan(events) == ["knowledge"]
    assert "SA-CTL-ART-178-179" in _refs(events)


def test_project_event_with_legal_term_is_still_reported(client):
    events = _dispatch(client, "MY-RAIL-A 业主今天通知要扣我们的误期违约金")
    assert "intake" in _plan(events)


def test_chinese_delay_damages_question_finds_the_saudi_clause(client):
    assert "SA-CTL-ART-178-179" in _refs(_dispatch(client, "沙特工程合同的误期违约金有什么规定？"))


def test_english_foreign_worker_question_finds_the_approval_clause(client):
    assert "MY-ACT265-S60K" in _refs(_dispatch(client, "Malaysia foreign worker permit requirements"))


def test_uncapped_delay_damages_are_high_risk():
    base = ("第1条 本合同适用马来西亚法律。第2条 付款：业主在收到付款申请后30天内支付。"
            "第3条 误期违约金：每延误一日按合同总价的1%计，{cap}。第4条 争议解决：提交吉隆坡仲裁。")
    def delay_risk(text):
        return [f["risk"] for f in review(text, "MY", "zh")["findings"] if f["category"] == "delay_damages"]
    assert delay_risk(base.format(cap="无上限")) == ["high"]
    assert delay_risk(base.format(cap="不设上限")) == ["high"]
    assert delay_risk(base.format(cap="累计不超过合同总价的10%")) == []
    english = ("Clause 5 Delay damages: 0.5% of the Contract Sum per day of delay, uncapped. "
               "Clause 6 Payment within 30 days. Clause 7 Disputes by arbitration in Dubai.")
    assert [f["risk"] for f in review(english, "AE", "en")["findings"] if f["category"] == "delay_damages"] == ["high"]
