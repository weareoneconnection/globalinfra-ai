import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# services/api is the package root uvicorn/Docker also run from
# (uvicorn app.main:app with cwd=services/api), so inserting it here lets us
# import the same `app.classify` module the running API serves, instead of
# duplicating the classification logic inside the eval harness.
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.classify import classify_text  # noqa: E402

DATASET = Path(__file__).parent / "datasets" / "cases.jsonl"
rows = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]


def check_row(row: dict) -> dict:
    """Run the classifier against both the English and Chinese text for a
    row and compare against the row's expected labels. Real assertions
    (did the predicted type/risk match?) replace the previous dataset
    schema check."""
    predicted_en = classify_text(row["text"])
    predicted_zh = classify_text(row.get("text_zh", "")) if row.get("text_zh") else predicted_en
    checks = {
        "type_en": predicted_en["type"] == row.get("expected_type"),
        "risk_en": predicted_en["risk"] == row.get("expected_risk"),
        "type_zh": predicted_zh["type"] == row.get("expected_type"),
        "risk_zh": predicted_zh["risk"] == row.get("expected_risk"),
    }
    return {
        "id": row["id"],
        "expected_type": row.get("expected_type"),
        "expected_risk": row.get("expected_risk"),
        "predicted_type_en": predicted_en["type"],
        "predicted_risk_en": predicted_en["risk"],
        "predicted_type_zh": predicted_zh["type"],
        "predicted_risk_zh": predicted_zh["risk"],
        "checks": checks,
        "pass": all(checks.values()),
    }


results = [check_row(row) for row in rows]
passed = sum(1 for r in results if r["pass"])
summary = {
    "dataset": "cases",
    "total": len(rows),
    "passed": passed,
    "pass_rate": passed / len(rows) if rows else 0.0,
    "results": results,
}
print(json.dumps(summary, indent=2, ensure_ascii=False))

# Make this a real CI gate: a regression in the classifier (or the dataset)
# now fails the build instead of always exiting 0.
if rows and passed < len(rows):
    sys.exit(1)
