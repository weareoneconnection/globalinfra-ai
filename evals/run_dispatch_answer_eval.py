#!/usr/bin/env python3
"""Answer-level evaluation of the dispatching assistant (deterministic, offline).

``run_dispatch_eval.py`` checks only which sub-agents a message is routed
to. This suite checks what comes back. Each of the 40 team-written messages
(Chinese, English, Arabic, Malay, Indonesian) goes to ``/assistant/dispatch``
with no model, so the rule planner and the retrieval path are measured:

- routing: the expected sub-agents, in order;
- evidence: a knowledge step returns at least one of the expected clauses
  (hit), or, for a comparison, sources from every named country;
- jurisdiction: no source from a country the question did not name
  (cross-country leakage);
- abstention: a question outside the corpus returns no source;
- progress: a progress step lists exactly the projects of the named country.

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
GATE_THRESHOLDS = {"routing": 95.0, "evidence_hit": 90.0, "no_leakage": 100.0, "abstention": 100.0, "progress_scope": 100.0}


def _rate(values: list[bool]) -> float | None:
    return round(100 * sum(values) / len(values), 1) if values else None


def main() -> int:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    with TestClient(app) as client:
        for row in rows:
            response = client.post("/assistant/dispatch?lang=zh", json={"message": row["message"]})
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            plan = next(e for e in events if e["type"] == "plan")
            agents = [s["agent"] for s in plan["steps"]]
            done = {e["index"]: e for e in events if e["type"] == "step_done"}
            expect = row["expect"]
            result = {"id": row["id"], "agents": agents, "routing": agents == row["agents"]}
            knowledge = next((done.get(i) for i, a in enumerate(agents) if a == "knowledge"), None)
            if knowledge is not None:
                hits = (knowledge.get("data") or {}).get("hits") or []
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
