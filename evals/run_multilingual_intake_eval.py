#!/usr/bin/env python3
"""Malay, Indonesian and Arabic intake evaluation (deterministic, offline).

Each case is a short field notice written in the local language. The rule
layer (``app.intake.build_intake_result`` with no model) must detect the
language, country, case type, risk, lifecycle stage and response deadline.

The 24 notices were written by the project team, and the keyword lists they
exercise were extended in the same change, so this measures coverage of the
rule vocabulary. It is not a held-out test, and the texts still need a
native-speaker check. A real model route (``LLM_MODE``) is not used here.
"""
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "services" / "api"
sys.path.insert(0, str(API))
os.environ["LLM_MODE"] = "mock"

from app.intake import build_intake_result  # noqa: E402

DATASET = API / "evals" / "multilingual_intake.jsonl"
FIELDS = ("language", "country", "type", "risk", "lifecycle", "deadline")
GATE_THRESHOLDS = {"language": 100.0, "country": 100.0, "type": 85.0, "risk": 85.0, "lifecycle": 80.0, "deadline": 80.0}
MIN_CASES_PER_LANGUAGE = 8


def _rate(values: list[bool]) -> float:
    return round(100 * sum(values) / max(len(values), 1), 1)


def main() -> int:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = []
    for row in rows:
        out = build_intake_result(row["text"])
        got = {
            "language": out["language"], "country": out["country"], "type": out["case_type"], "risk": out["risk"],
            "lifecycle": out["lifecycle_stage"]["id"], "deadline": (out["deadline"] or {}).get("en"),
        }
        want = {key: row[f"expected_{key}"] for key in FIELDS}
        results.append({"id": row["id"], "language": row["language"], "predicted": got, "expected": want,
                        "correct": {key: got[key] == want[key] for key in FIELDS}})
    metrics = {key: _rate([r["correct"][key] for r in results]) for key in FIELDS}
    metrics["case_exact"] = _rate([all(r["correct"].values()) for r in results])
    for lang in sorted({r["language"] for r in results}):
        subset = [r for r in results if r["language"] == lang]
        metrics[f"case_exact_{lang}"] = _rate([all(r["correct"].values()) for r in subset])
    per_language = Counter(r["language"] for r in results)
    gates = {key: metrics[key] >= threshold for key, threshold in GATE_THRESHOLDS.items()}
    gates["coverage"] = all(per_language.get(lang, 0) >= MIN_CASES_PER_LANGUAGE for lang in ("ms", "id", "ar"))
    passed = all(gates.values())
    print(json.dumps({"suite": "MULTILINGUAL_INTAKE", "total_cases": len(results), "status": "PASSED" if passed else "FAILED",
                      "cases_per_language": dict(sorted(per_language.items())), "metrics": metrics,
                      "thresholds": GATE_THRESHOLDS, "gates": gates, "cases": results}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
