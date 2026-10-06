"""Evaluation harness for the V1.3 M1 Universal Intake path.

Complements ``run_eval.py`` (which exercises ``classify.py`` directly) by
asserting the full deterministic intake engine -- the Layer-1 case_type/risk
*and* the enrichment that drives specialist-team routing and country-based
project selection -- against ``datasets/intake.jsonl``. It imports the same
``app.intake`` module the running API serves, so a regression in intake fails
the build instead of silently passing.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.intake import build_intake_result  # noqa: E402

DATASET = Path(__file__).parent / "datasets" / "intake.jsonl"
rows = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]


def check_row(row: dict) -> dict:
    """Run intake against both the English and Chinese text for a row and
    compare case_type, risk, specialist routing and detected country."""
    pred_en = build_intake_result(row["text"])
    pred_zh = build_intake_result(row["text_zh"]) if row.get("text_zh") else pred_en
    checks = {
        "type_en": pred_en["case_type"] == row.get("expected_case_type"),
        "risk_en": pred_en["risk"] == row.get("expected_risk"),
        "type_zh": pred_zh["case_type"] == row.get("expected_case_type"),
        "agents_en": pred_en["recommended_agents"] == row.get("expected_agents"),
        "country_en": pred_en["country"] == row.get("expected_country"),
    }
    return {
        "id": row["id"],
        "expected_type": row.get("expected_case_type"),
        "predicted_type_en": pred_en["case_type"],
        "predicted_risk_en": pred_en["risk"],
        "predicted_agents_en": pred_en["recommended_agents"],
        "predicted_country_en": pred_en["country"],
        "checks": checks,
        "pass": all(checks.values()),
    }


results = [check_row(row) for row in rows]
passed = sum(1 for r in results if r["pass"])
summary = {
    "dataset": "intake",
    "total": len(rows),
    "passed": passed,
    "pass_rate": passed / len(rows) if rows else 0.0,
    "results": results,
}
print(json.dumps(summary, indent=2, ensure_ascii=False))

if rows and passed < len(rows):
    sys.exit(1)
