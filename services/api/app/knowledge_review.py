"""Expert and native-speaker review records for the clause library and glossaries.

A review record is written only by ``scripts/import_review.py`` from a review
packet that a named-role reviewer filled in. Records carry the reviewer's
role, qualification and organisation type plus a reference to the signed
packet, not personal contact details. Nothing here marks an item reviewed
without such a record.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

REVIEWS_DIR = Path(__file__).resolve().parent / "knowledge_data" / "reviews"
VERDICTS = {"ACCURATE", "MINOR_CORRECTION", "INACCURATE"}
ITEM_TYPES = {"clause", "term"}
REQUIRED_FIELDS = (
    "item_type", "item_id", "verdict", "packet_id", "reviewer_role", "reviewer_qualification",
    "reviewer_organisation_type", "reviewed_on", "evidence_ref",
)
# What a verdict does to the item. INACCURATE withdraws a clause from search
# until it is corrected and re-reviewed.
CLAUSE_STATUS = {
    "ACCURATE": ("EXPERT_REVIEWED", "CURRENT"),
    "MINOR_CORRECTION": ("REVIEWED_CORRECTION_PENDING", "CURRENT"),
    "INACCURATE": ("REVIEWED_INACCURATE", "UNDER_REVISION"),
}
TERM_STATUS = {"ACCURATE": "NATIVE_REVIEWED", "MINOR_CORRECTION": "REVIEWED_CORRECTION_PENDING", "INACCURATE": "REVIEWED_INACCURATE"}


def validate_review(record: dict) -> dict:
    missing = [key for key in REQUIRED_FIELDS if not record.get(key)]
    if missing:
        raise ValueError(f"review record missing: {', '.join(missing)}")
    if record["verdict"] not in VERDICTS:
        raise ValueError(f"unknown verdict {record['verdict']!r}")
    if record["item_type"] not in ITEM_TYPES:
        raise ValueError(f"unknown item_type {record['item_type']!r}")
    if record["verdict"] != "ACCURATE" and not (record.get("correction") or record.get("comment")):
        raise ValueError(f"{record['item_id']}: a non-ACCURATE verdict needs a correction or comment")
    return record


def load_reviews(directory: Path = REVIEWS_DIR) -> list[dict]:
    if not directory.exists():
        return []
    rows: list[dict] = []
    for path in sorted(directory.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            rows.extend(validate_review(json.loads(line)) for line in handle if line.strip())
    return rows


def latest_reviews(item_type: str, reviews: list[dict] | None = None) -> dict[str, dict]:
    """The most recent review per item id (later records supersede earlier ones)."""
    latest: dict[str, dict] = {}
    for row in sorted(reviews if reviews is not None else load_reviews(), key=lambda r: r["reviewed_on"]):
        if row["item_type"] == item_type:
            latest[row["item_id"]] = row
    return latest


def review_summary(clause_ids: list[str], term_ids: list[str], reviews: list[dict] | None = None) -> dict:
    reviews = reviews if reviews is not None else load_reviews()
    clauses, terms = latest_reviews("clause", reviews), latest_reviews("term", reviews)
    return {
        "records": len(reviews),
        "clauses_reviewed": sum(cid in clauses for cid in clause_ids),
        "clauses_total": len(clause_ids),
        "clause_verdicts": dict(Counter(row["verdict"] for cid, row in clauses.items() if cid in set(clause_ids))),
        "terms_reviewed": sum(tid in terms for tid in term_ids),
        "terms_total": len(term_ids),
        "term_verdicts": dict(Counter(row["verdict"] for tid, row in terms.items() if tid in set(term_ids))),
        "reviewers": sorted({(row["reviewer_role"], row["reviewer_organisation_type"]) for row in reviews}),
        "packets": sorted({row["packet_id"] for row in reviews}),
    }
