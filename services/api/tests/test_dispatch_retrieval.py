"""Country-aware, multilingual knowledge search behind the dispatcher (P0)."""
import json

from app.assistant import core_query
from app.intake import detect_countries
from app.retrieval import tokenize_bigrams


def _dispatch(client, message):
    response = client.post("/assistant/dispatch?lang=zh", json={"message": message})
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def _knowledge_hits(events, agent="knowledge"):
    plan = next(e for e in events if e["type"] == "plan")
    index = next(s["index"] for s in plan["steps"] if s["agent"] == agent)
    done = next(e for e in events if e["type"] == "step_done" and e["index"] == index)
    return done["data"]


def test_query_helpers():
    assert detect_countries("比较马来西亚和沙特的规定") == ["MY", "SA"]
    assert detect_countries("ما هي مكافأة نهاية الخدمة في الإمارات؟") == ["AE"]
    assert core_query("Indonesia level crossing railway regulation") == "level crossing railway"
    tokens = tokenize_bigrams("Level crossings and end-of-service gratuity")
    assert {"crossing", "end", "service"} <= set(tokens)


def test_single_country_question_stays_in_that_country(client):
    data = _knowledge_hits(_dispatch(client, "沙特工人斋月期间每天最多工作几小时？"))
    assert data["countries"] == ["SA"]
    assert data["hits"][0]["source_ref"] == "SA-LABOR-ART-98"
    assert {h["country_code"] for h in data["hits"]} <= {"SA", None}


def test_arabic_question_finds_the_clause(client):
    data = _knowledge_hits(_dispatch(client, "ما هي مكافأة نهاية الخدمة في الإمارات؟"))
    assert "AE-FDL33-2021-ART-51" in [h["source_ref"] for h in data["hits"]]


def test_comparison_keeps_both_countries(client):
    data = _knowledge_hits(_dispatch(client, "比较马来西亚和沙特对工伤的规定"), agent="compare")
    assert data["countries"] == ["MY", "SA"]
    assert [row["country"] for row in data["table"]] == ["MY", "SA"]
    assert all(row["clauses"] and {c["country_code"] for c in row["clauses"]} == {row["country"]} for row in data["table"])


def test_progress_follows_the_named_country(client):
    events = _dispatch(client, "阿联酋分包商有什么法律规定？另外查一下马来西亚项目进度")
    progress = next(e for e in events if e["type"] == "step_done" and e["data"].get("projects") is not None)
    codes = [p["code"] for p in progress["data"]["projects"]]
    assert "MY-RAIL-A" in codes and progress["data"]["countries"] == ["MY"]
    assert not any(code.startswith(("AE-", "SA-", "ID-")) for code in codes)  # other tests may add MY projects


def test_off_topic_question_returns_nothing(client):
    assert _knowledge_hits(_dispatch(client, "how to cook rice?"))["hits"] == []
