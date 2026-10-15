#!/usr/bin/env python3
"""Dispatching assistant evaluation (deterministic, offline).

Each synthetic message is sent to ``/assistant/dispatch``. Checks: the plan
names exactly the expected sub-agents in order, every planned step reports
back, no step fails, and a multi-step plan ends with a summary.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "services" / "api"
sys.path.insert(0, str(API))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/dispatch_eval.db")
os.environ["LLM_MODE"] = "mock"
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

DATASET = API / "evals" / "assistant_dispatch.jsonl"
GATES = {"plan_accuracy": 100.0, "step_completion": 100.0, "summary_coverage": 100.0}


def main() -> int:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    with TestClient(app) as client:
        for row in rows:
            response = client.post("/assistant/dispatch?lang=zh", json={"message": row["message"]})
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            plan = next(e for e in events if e["type"] == "plan")
            agents = [s["agent"] for s in plan["steps"]]
            done = [e for e in events if e["type"] == "step_done"]
            summary = any(e["type"] == "summary" for e in events)
            results.append({
                "id": row["id"], "agents": agents, "plan_ok": agents == row["agents"],
                "completed": len(done) == len(agents) and all(e["status"] == "ok" for e in done),
                "summary_ok": summary == (len(agents) > 1),
            })
    n = len(results)
    metrics = {
        "plan_accuracy": round(100 * sum(r["plan_ok"] for r in results) / n, 1),
        "step_completion": round(100 * sum(r["completed"] for r in results) / n, 1),
        "summary_coverage": round(100 * sum(r["summary_ok"] for r in results) / n, 1),
        "multi_step_share": round(100 * sum(len(r["agents"]) > 1 for r in results) / n, 1),
    }
    passed = all(metrics[k] >= v for k, v in GATES.items())
    print(json.dumps({"suite": "ASSISTANT_DISPATCH", "total_cases": n, "status": "PASSED" if passed else "FAILED",
                      "metrics": metrics, "gates": GATES, "cases": results}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
