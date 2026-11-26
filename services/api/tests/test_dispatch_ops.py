"""Lifecycle sub-agents: contract review, precedents, digital twin,
commissioning, project briefing and the schedule/cost upgrade of progress.

Contract texts below are synthetic, written by the team for testing.
"""
import json

import pytest

from app.contract_review import looks_like_contract, review
from app.dispatcher import AGENTS, PlanContext, dispatch_rules

PROJECTS = {"MY-RAIL-A": 1, "ID-HWY-B": 2, "SA-METRO-C": 3}
MY_SUBCONTRACT = ("请审查以下分包合同条款的风险：第5条 付款：总包方在收到业主付款后30天内向分包方支付进度款。"
                  "第8条 误期违约金：分包方每延误一天按合同价0.5%支付违约金。"
                  "第12条 索赔：分包方应在事件发生后7天内提出索赔通知，否则视为放弃。"
                  "第15条 保留金：每期扣留15%作为保留金。本合同适用马来西亚法律。")
AE_CONTRACT = ("Please review this contract for risk. Clause 4: The Employer shall pay within 45 days of the invoice. "
               "Clause 9: The Contractor shall not be liable for any structural defect or collapse after taking-over. "
               "Clause 11: Delay damages of AED 20,000 per day, capped at 10% of the Contract Price. "
               "Clause 20: Disputes shall be settled by arbitration in Dubai. Clause 21: Force majeure relieves both parties. "
               "This Contract is governed by the laws of the United Arab Emirates.")


def _ctx():
    return PlanContext(project_codes=PROJECTS, known_case_ids=set())


def _dispatch(client, message):
    response = client.post("/assistant/dispatch?lang=zh", json={"message": message})
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def _done(events, agent):
    plan = next(e for e in events if e["type"] == "plan")["steps"]
    index = next(s["index"] for s in plan if s["agent"] == agent)
    return next(e for e in events if e["type"] == "step_done" and e["index"] == index)


@pytest.mark.parametrize("message, agents", [
    (MY_SUBCONTRACT, ["contract_review"]),
    ("尊敬的承包商：根据合同第14.2条，贵方须在7日内恢复便道并书面答复。", ["intake"]),   # a letter citing a clause
    ("P47 桥墩现在状态怎么样？", ["twin"]),
    ("有哪些传感器告警？", ["twin"]),
    ("哪些系统还不能移交？", ["commissioning"]),
    ("以前有没有类似的便道纠纷案例？", ["precedents"]),
    ("今天 MY-RAIL-A 有什么要处理的？", ["briefing"]),
    ("MY-RAIL-A 进度怎么样？如果顺延 20 天呢？", ["progress"]),
    ("马来西亚铁路运维有什么规定？", ["knowledge"]),
    ("P47 墩昨天发生坍塌事故，以前有没有类似的事故案例？", ["intake", "precedents"]),
])
def test_routing(message, agents):
    assert [s.agent for s in dispatch_rules(message, _ctx())] == agents


def test_precedents_wait_for_the_new_work_order():
    steps = dispatch_rules("P47 墩昨天发生坍塌事故，以前有没有类似的事故案例？", _ctx())
    assert steps[1].depends_on == [0]


# --- contract review (deterministic rules) --------------------------------------

def test_malaysian_pay_when_paid_is_flagged_with_cipaa():
    result = review(MY_SUBCONTRACT, "MY", "zh")
    by = {(f["category"], f["risk"]): f for f in result["findings"]}
    assert by[("payment", "high")]["basis"] == ["MY-ACT746-S35"]
    assert ("delay_damages", "high") in by                      # no cap
    assert "7 天" in by[("claims", "high")]["finding"]          # short time bar
    assert ("retention", "medium") in by                        # 15% retention
    assert not any(f["category"] == "dispute" for f in result["findings"])  # governing law is present
    assert any(f["category"] == "force_majeure" for f in result["findings"])  # missing


def test_uae_exclusion_of_structural_liability_cites_decennial_rule():
    result = review(AE_CONTRACT, "AE", "en")
    liability = [f for f in result["findings"] if f["category"] == "liability"]
    assert liability and liability[0]["risk"] == "high" and liability[0]["basis"] == ["AE-FDL25-2025-ART-823"]
    assert not any(f["category"] == "delay_damages" for f in result["findings"])  # capped
    assert not any(f["category"] in {"dispute", "force_majeure"} for f in result["findings"])


def test_law_is_cited_only_for_the_country_it_belongs_to():
    for country in ("SA", "ID", None):
        result = review(MY_SUBCONTRACT, country, "zh")
        assert all(not f["basis"] for f in result["findings"])


def test_letters_and_questions_are_not_contracts():
    assert looks_like_contract(MY_SUBCONTRACT)
    assert not looks_like_contract("合同里的违约金一般怎么约定？")
    assert not looks_like_contract("尊敬的承包商：根据合同第14.2条，贵方须在7日内恢复便道并书面答复，否则我方将按合同第20条追究。")


def test_contract_review_step(client):
    step = _done(_dispatch(client, MY_SUBCONTRACT), "contract_review")
    assert step["status"] == "ok" and step["data"]["country"] == "MY"
    assert "MY-ACT746-S35" in step["refs"] and "不构成法律意见" in step["summary"]
    assert all(r["country_code"] == "MY" for r in step["data"]["related"])


# --- operations agents -----------------------------------------------------------

def test_twin_reports_the_named_asset_only(client):
    step = _done(_dispatch(client, "P47 桥墩现在状态怎么样？"), "twin")
    matched = step["data"]["matched"]
    assert "TWIN-MYRAIL-V12-P47" in matched and all(m.endswith("-P47") for m in matched)  # other tests may add a P47
    assert not any(a["twin_id"].endswith("AHU01") for a in step["data"]["alerts"])        # the AHU alarm is another asset
    assert "WO-2026-0998" in step["summary"]


def test_twin_lists_sensor_alarms(client):
    step = _done(_dispatch(client, "有哪些传感器告警？"), "twin")
    assert [a["id"] for a in step["data"]["alerts"]] == ["SNS-VIB-AHU01"]
    assert "预警值 4.5" in step["summary"]


def test_commissioning_readiness(client):
    items = _done(_dispatch(client, "哪些系统还不能移交？"), "commissioning")["data"]["items"]
    assert items and all(i["ready"] == (i["readiness"] >= 95 and i["punch_open"] == 0) for i in items)


def test_precedents_say_when_none_is_closed(client):
    step = _done(_dispatch(client, "以前有没有类似的便道纠纷案例？"), "precedents")
    assert "CASE-2026-0182" in [p["case_id"] for p in step["data"]["precedents"]]
    assert all(not p["resolved"] for p in step["data"]["precedents"]) and "暂无已办结" in step["summary"]


def test_precedents_never_return_the_new_case(client):
    events = _dispatch(client, "P47 墩昨天发生坍塌事故，以前有没有类似的事故案例？")
    new_case = _done(events, "intake")["case_id"]
    step = _done(events, "precedents")
    assert step["data"]["excluded"] == [new_case]
    assert new_case not in [p["case_id"] for p in step["data"]["precedents"]]


def test_briefing_counts(client):
    step = _done(_dispatch(client, "今天 MY-RAIL-A 有什么要处理的？"), "briefing")
    counts = step["data"]["counts"]
    assert step["data"]["project_ids"] == [1]
    assert counts["alerts"] == 1 and counts["cases"] >= 3
    assert any(i["kind"] == "schedule" for i in step["data"]["items"])  # MY-RAIL-A is 18 days behind


def test_progress_reports_cost_and_extension_effect(client):
    step = _done(_dispatch(client, "MY-RAIL-A 进度怎么样？如果顺延 20 天呢？"), "progress")
    project = step["data"]["projects"][0]
    assert project["headroom_m"] == round(project["budget_m"] - project["forecast_m"], 1)
    assert step["data"]["eot_requested_days"] == 20 and project["variance_after_eot"] == project["schedule_variance"] + 20


def test_self_knowledge_counts_every_agent(client):
    events = _dispatch(client, "你能做什么？")
    step = next(e for e in events if e["type"] == "step_done")
    assert f"{len(AGENTS)} 个子智能体" in step["summary"] and len(AGENTS) == 18
