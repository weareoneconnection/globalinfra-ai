#!/usr/bin/env python3
"""Answer-level evaluation of the dispatching assistant (deterministic, offline).

``run_dispatch_eval.py`` checks only which sub-agents a message is routed
to. This suite checks what comes back. Each of the 50 team-written messages
(Chinese, English, Arabic, Malay, Indonesian) goes to ``/assistant/dispatch``
with no model, so the rule planner and the retrieval path are measured:

- routing: the expected sub-agents, in order;
- evidence: a knowledge step returns at least one of the expected clauses
  (hit), or, for a comparison, sources from every named country;
- jurisdiction: no source from a country the question did not name
  (cross-country leakage);
- abstention: a question outside the corpus returns no source;
- progress: a progress step lists exactly the projects of the named country;
- sub-agents (P1): a comparison reports a country the library has no clause
  for instead of filling its cell; the glossary returns the expected local term, the permit
  gates come from the right stage and country, a drawing question without a
  drawing number never guesses one, and a reply draft is marked not sent,
  waits for the steps it depends on and cites only clauses they retrieved;
- focus (P2): a follow-up in the same session ("and overtime?") searches the
  country the conversation is about, or the one the follow-up names.

Clause ids were chosen by the team from the shipped clause library. With a
model configured the planner and the wording of the answer change; that run
is reported separately and is not part of this gate.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "services" / "api"
sys.path.insert(0, str(API))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/dispatch_answer_eval.db")
os.environ["LLM_MODE"] = "mock"
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

DATASET = API / "evals" / "dispatch_answers.jsonl"
GATE_THRESHOLDS = {"routing": 95.0, "evidence_hit": 90.0, "no_leakage": 100.0, "abstention": 100.0, "progress_scope": 100.0,
                   "sub_agents": 100.0, "draft_grounded": 100.0, "focus": 100.0}


def _dispatch(client, message, session_id=None):
    body = {"message": message, **({"session_id": session_id} if session_id else {})}
    response = client.post("/assistant/dispatch?lang=zh", json=body)
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def _step(agents, done, agent):
    return next((done.get(i) for i, a in enumerate(agents) if a == agent), None)


def _rate(values: list[bool]) -> float | None:
    return round(100 * sum(values) / len(values), 1) if values else None


def main() -> int:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    with TestClient(app) as client:
        for row in rows:
            events = _dispatch(client, row["message"])
            plan = next(e for e in events if e["type"] == "plan")
            agents = [s["agent"] for s in plan["steps"]]
            done = {e["index"]: e for e in events if e["type"] == "step_done"}
            expect = row["expect"]
            result = {"id": row["id"], "agents": agents, "routing": agents == row["agents"]}
            knowledge = _step(agents, done, "knowledge") or _step(agents, done, "compare")
            if knowledge is not None:
                data = knowledge.get("data") or {}
                hits = data.get("hits") or [c for row_ in data.get("table") or [] for c in row_["clauses"]]
                refs = [h["source_ref"] for h in hits]
                countries = {h["country_code"] for h in hits if h.get("country_code")}
                result.update(refs=refs, searched=(knowledge.get("data") or {}).get("countries"))
                if expect.get("abstain"):
                    result["abstention"] = not refs
                if expect.get("refs"):
                    result["evidence_hit"] = any(ref in refs for ref in expect["refs"])
                if expect.get("refs_from_countries"):
                    result["evidence_hit"] = set(expect["refs_from_countries"]) <= countries
                if expect.get("countries"):
                    result["no_leakage"] = countries <= set(expect["countries"])
            progress = next((done.get(i) for i, a in enumerate(agents) if a == "progress"), None)
            if progress is not None and "projects" in expect:
                codes = [p["code"] for p in (progress.get("data") or {}).get("projects", [])]
                result.update(projects=codes, progress_scope=sorted(codes) == sorted(expect["projects"]))
            if expect.get("gap_countries"):
                # The library has no clause for that country: the comparison must say so, not fill the cell.
                table = {row_["country"]: row_["clauses"] for row_ in ((knowledge or {}).get("data") or {}).get("table") or []}
                result["sub_agents"] = all(c in table and not table[c] for c in expect["gap_countries"]) and \
                    "未找到" in (knowledge or {}).get("summary", "")
            glossary, gates, drawing, draft = (_step(agents, done, a) for a in ("glossary", "gates", "drawing", "draft"))
            if "terms" in expect and glossary is not None:
                terms = (glossary.get("data") or {}).get("terms") or []
                result["terms"] = [(t["country"], t["local"]) for t in terms]
                result["sub_agents"] = all(any(t["country"] == c and (local is None or t["local"] == local) for t in terms)
                                           for c, local in expect["terms"].items())
            elif "terms" in expect:
                result["sub_agents"] = False
            if "gates" in expect:
                data = (gates or {}).get("data") or {}
                result["sub_agents"] = (data.get("stage") == expect["gates"]["stage"]
                                        and data.get("countries") == expect["gates"]["countries"]
                                        and all(row_["gates"] for row_ in data.get("gates") or [{}]))
            if expect.get("drawing_no_guess"):
                result["sub_agents"] = drawing is not None and "drawing_id" not in (drawing.get("data") or {})
            if expect.get("draft"):
                retrieved = {ref for i, a in enumerate(agents) if a != "draft" for ref in (done.get(i) or {}).get("refs") or []}
                data = (draft or {}).get("data") or {}
                starts = [e["index"] for e in events if e["type"] == "step_start"]
                draft_index = agents.index("draft") if "draft" in agents else None
                result["draft_grounded"] = bool(
                    draft and draft["status"] == "ok" and data.get("status") == "DRAFT_NOT_SENT"
                    and all(set(p["refs"]) <= retrieved for p in data.get("points") or [])
                    and draft_index is not None
                    and all(starts.index(d) < starts.index(draft_index) for d in plan["steps"][draft_index]["depends_on"]))
            if row.get("follow_up"):
                session_id = next(e for e in events if e["type"] == "session")["session_id"]
                follow = _dispatch(client, row["follow_up"], session_id)
                follow_plan = next(e for e in follow if e["type"] == "plan")["steps"]
                follow_done = {e["index"]: e for e in follow if e["type"] == "step_done"}
                step = _step([s["agent"] for s in follow_plan], follow_done, "knowledge") or {}
                data = step.get("data") or {}
                found = {h["country_code"] for h in data.get("hits") or [] if h.get("country_code")}
                result.update(follow_up_countries=data.get("countries"),
                              focus=data.get("countries") == expect["follow_up_countries"]
                              and bool(found) and found <= set(expect["follow_up_countries"]))
            results.append(result)
    metrics = {key: _rate([r[key] for r in results if key in r]) for key in GATE_THRESHOLDS}
    for lang, ids in {"ar": ("A13", "A14", "A15", "A20"), "ms_id": ("A16", "A17", "A18", "A19")}.items():
        metrics[f"evidence_hit_{lang}"] = _rate([r["evidence_hit"] for r in results if r["id"] in ids and "evidence_hit" in r])
    gates = {key: metrics[key] is not None and metrics[key] >= threshold for key, threshold in GATE_THRESHOLDS.items()}
    passed = all(gates.values())
    print(json.dumps({"suite": "DISPATCH_ANSWERS", "total_cases": len(results), "status": "PASSED" if passed else "FAILED",
                      "metrics": metrics, "thresholds": GATE_THRESHOLDS, "gates": gates, "cases": results},
                     ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
