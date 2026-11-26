#!/usr/bin/env python3
"""Import a filled review packet as review records.

Usage:
    python scripts/import_review.py --packet /secure/review/MY-clauses.csv \\
        --reviewer-role "Construction lawyer" --reviewer-qualification "Advocate & Solicitor, High Court of Malaya" \\
        --reviewer-organisation-type "Law firm" --reviewed-on 2026-12-01 --evidence-ref "signed cover sheet, file ref ..."

Writes services/api/app/knowledge_data/reviews/<packet_id>.jsonl. Only the
reviewer's role, qualification and organisation type are recorded; a name is
optional (--reviewer-name) and only with the reviewer's consent. Rows with an
empty verdict are skipped and reported, never defaulted to ACCURATE.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.country_knowledge import load_clause_library, load_glossary  # noqa: E402
from app.knowledge_review import REVIEWS_DIR, validate_review  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--reviewer-role", required=True)
    parser.add_argument("--reviewer-qualification", required=True)
    parser.add_argument("--reviewer-organisation-type", required=True)
    parser.add_argument("--reviewer-name", help="only with the reviewer's written consent")
    parser.add_argument("--reviewed-on", required=True, help="YYYY-MM-DD")
    parser.add_argument("--evidence-ref", required=True, help="where the signed cover sheet is kept")
    parser.add_argument("--out-dir", type=Path, default=REVIEWS_DIR)
    args = parser.parse_args()

    reviewed_on = date.fromisoformat(args.reviewed_on)
    if reviewed_on > date.today():
        print("REFUSED: reviewed_on is in the future.", file=sys.stderr)
        return 2
    known = {row["id"] for row in load_clause_library()}
    for code in ("MY", "ID"):
        known |= {row["id"] for row in load_glossary(code)}

    with args.packet.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    records, skipped, errors = [], [], []
    for row in rows:
        verdict = (row.get("verdict") or "").strip().upper()
        if not verdict:
            skipped.append(row["item_id"])
            continue
        if row["item_id"] not in known:
            errors.append(f"{row['item_id']}: not in the library")
            continue
        record = {
            "item_type": row["item_type"], "item_id": row["item_id"], "verdict": verdict,
            "correction": (row.get("correction") or "").strip(), "comment": (row.get("comment") or "").strip(),
            "packet_id": row["packet_id"], "reviewer_role": args.reviewer_role,
            "reviewer_qualification": args.reviewer_qualification,
            "reviewer_organisation_type": args.reviewer_organisation_type,
            "reviewed_on": reviewed_on.isoformat(), "evidence_ref": args.evidence_ref,
        }
        if args.reviewer_name:
            record["reviewer_name"] = args.reviewer_name
        try:
            records.append(validate_review(record))
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        print("REFUSED:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 2
    if not records:
        print("No filled verdicts in the packet.", file=sys.stderr)
        return 1
    packet_ids = {r["packet_id"] for r in records}
    if len(packet_ids) != 1:
        print("REFUSED: a file must hold one packet.", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"{packet_ids.pop()}.jsonl"
    with out.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({"written": str(out), "records": len(records), "verdicts": Counter(r["verdict"] for r in records),
                      "skipped_unfilled": len(skipped)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
