#!/usr/bin/env python3
"""Agent organization evaluation (deterministic, offline).

Each synthetic case goes through intake and the agent organization. Checks:
team composition (required members present, excluded members absent),
whether agents ask the project team for input and escalate unresolved
conflicts when expected, plan traceability, and that every SUPPORTED finding
cites evidence its own tools retrieved.

Escalation expectations (``expect_question`` / ``expect_unresolved``) are
asserted only where the seeded knowledge base makes the outcome
determinable; ``null`` means "not asserted". Known limitations of the
deterministic path on this small corpus: a generic engineering note can
clear the confidence threshold for unrelated letters, and an agent without
discipline-specific sources may ask for information the letter already
contains.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "services" / "api"
sys.path.insert(0, str(API))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/agent_org_eval.db")
os.environ["LLM_MODE"] = "mock"
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

DATASET = API / "evals" / "agent_org.jsonl"
GATES = {"team_accuracy": 100.0, "escalation_accuracy": 100.0, "plan_traceability": 100.0, "grounded_findings": 100.0}


def main() -> int:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    with TestClient(app) as client:
        for row in rows:
            body = client.post("/intake/text", json={"text": row["text"], "project_id": 1}).json()
            run = client.get(f"/cases/{body['case_id']}/agent-run").json()
            team = [m["agent_id"] for m in run["team"]]
            team_ok = all(a in team for a in row["team_includes"]) and not any(a in team for a in row["team_excludes"])
            escalation_ok = True
            if row["expect_question"] is not None:
                escalation_ok &= bool(run["questions"]) == row["expect_question"]
            if row["expect_unresolved"] is not None:
                escalation_ok &= bool(run["unresolved"]) == row["expect_unresolved"]
            traceable = bool(run["plan"]) and all(step["source"] for step in run["plan"])
            grounded = all(
                f["status"] != "SUPPORTED" or (f["evidence_refs"] and all(
                    ref in {h["source_ref"] for t in f["tool_calls"] if t["tool"] == "knowledge.search" for h in t["output"]["hits"]}
                    for ref in f["evidence_refs"]))
                for f in run["findings"]
            )
            results.append({"id": row["id"], "team": team, "team_ok": team_ok, "escalation_ok": escalation_ok,
                            "traceable": traceable, "grounded": grounded,
                            "questions": len(run["questions"]), "unresolved": len(run["unresolved"])})
    n = len(results)
    metrics = {
        "team_accuracy": round(100 * sum(r["team_ok"] for r in results) / n, 1),
        "escalation_accuracy": round(100 * sum(r["escalation_ok"] for r in results) / n, 1),
        "plan_traceability": round(100 * sum(r["traceable"] for r in results) / n, 1),
        "grounded_findings": round(100 * sum(r["grounded"] for r in results) / n, 1),
        "avg_team_size": round(sum(len(r["team"]) for r in results) / n, 2),
    }
    passed = all(metrics[k] >= v for k, v in GATES.items())
    print(json.dumps({"suite": "AGENT_ORGANIZATION", "total_cases": n, "status": "PASSED" if passed else "FAILED",
                      "metrics": metrics, "gates": GATES, "cases": results}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
