"""The assistant's self-knowledge: answered from the live roster and the
clause library's coverage, and honest about what it cannot answer."""
import json

import pytest

from app.capabilities import DOMAIN_IDS, coverage, coverage_gaps, detect_domains, library_stats, level
from app.country_knowledge import load_clause_library
from app.dispatcher import AGENTS, PlanContext, dispatch_rules


def _ctx():
    return PlanContext(project_codes={"MY-RAIL-A": 1}, known_case_ids=set())


def _dispatch(client, message):
    response = client.post("/assistant/dispatch?lang=zh", json={"message": message})
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def _step(events, agent):
    plan = next(e for e in events if e["type"] == "plan")["steps"]
    index = next(s["index"] for s in plan if s["agent"] == agent)
    return next(e for e in events if e["type"] == "step_done" and e["index"] == index)


@pytest.mark.parametrize("message, agents", [
    ("你能做什么？", ["self"]),
    ("你好", ["self"]),
    ("你能分析合同吗？", ["self"]),
    ("帮我分析这份合同的主要风险", ["self"]),
    ("你能回答沙特的质量问题吗？", ["self"]),
    ("Can you answer UAE building code questions?", ["self"]),
    ("能不能查一下马来西亚脚手架要求？", ["knowledge"]),          # a polite lookup, not about the assistant
    ("你能告诉我马来西亚脚手架要求吗？", ["knowledge"]),
    ("沙特合同延误的违约金有什么规定？", ["knowledge"]),          # a rule question naming a delay
    ("阿联酋工程缺陷责任期多长？", ["knowledge"]),                # a rule question naming a defect
    ("P47 墩昨天发生坍塌事故", ["intake"]),                      # an event is still a report
    ("马来西亚外籍工人需要什么许可？", ["knowledge"]),            # worker permits are labour law, not project gates
    ("沙特项目施工阶段需要哪些许可？", ["gates"]),
])
def test_routing(message, agents):
    assert [s.agent for s in dispatch_rules(message, _ctx())] == agents


def test_coverage_is_counted_from_the_library():
    rows = load_clause_library()
    stats = library_stats()
    assert stats["clauses"] == len(rows) and stats["countries"] == 4
    table = {row["id"]: row for row in coverage("zh")}
    assert set(table) == set(DOMAIN_IDS)
    for row in table.values():
        assert sum(cell["clauses"] for cell in row["countries"].values()) <= len(rows)
    # Building codes are never claimed: the library holds laws, not technical provisions.
    assert all(cell["level"] in {"legal_only", "none"} for cell in table["building_codes"]["countries"].values())
    assert level("safety", "MY") == "covered"
    assert level("environment", "ID") == "none"


def test_overview_names_every_agent_and_the_gaps(client):
    step = _step(_dispatch(client, "你能做什么？"), "self")
    data = step["data"]
    assert len(data["agents"]) == len(AGENTS) and {a["id"] for a in data["agents"]} == set(AGENTS)
    assert f"{len(AGENTS)} 个子智能体" in step["summary"]
    assert "建筑与设计规范" in step["summary"].split("较少或没有")[1]
    assert data["boundaries"]


def test_country_question_is_scoped_to_that_country(client):
    data = _step(_dispatch(client, "你能回答沙特的质量问题吗？"), "self")["data"]
    assert data["focus_domains"] == ["quality"]
    assert all(set(row["countries"]) == {"SA"} for row in data["coverage"])


def test_contract_review_request_explains_how(client):
    summary = _step(_dispatch(client, "帮我分析这份合同的主要风险"), "self")["summary"]
    assert "合同审查智能体" in summary and "粘贴" in summary


def test_building_code_question_states_the_gap_and_no_number(client):
    step = _step(_dispatch(client, "沙特建筑规范对混凝土保护层厚度有什么要求？"), "knowledge")
    assert step["data"]["coverage_gaps"] and "技术条文" in step["summary"]
    assert not any(ch.isdigit() for ch in step["data"]["coverage_gaps"][0])


def test_gaps_only_for_cells_the_library_lacks():
    assert detect_domains("马来西亚脚手架安全要求") == ["safety"]
    assert coverage_gaps(["safety"], ["MY"], "zh") == []
    assert coverage_gaps(["environment"], ["ID"], "zh")


def test_gates_without_a_stage_gate_fall_back_to_clauses(client):
    step = _step(_dispatch(client, "马来西亚铁路开通运营需要什么许可？"), "gates")
    assert step["data"]["stage"] == "operations"
    assert any(ref.startswith("MY-ACT463") for ref in step["refs"])
