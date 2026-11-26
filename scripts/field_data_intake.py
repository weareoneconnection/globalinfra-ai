#!/usr/bin/env python3
"""De-identify authorized field documents for the GlobalInfra knowledge base.

Usage:
    python scripts/field_data_intake.py \\
        --input  /secure/raw/ecrl-letters \\
        --authorization /secure/raw/AUTHORIZATION.json \\
        --project-code ECRL-DEMO --country MY --document-type CORRESPONDENCE \\
        [--names /secure/raw/names.txt] [--aliases /secure/raw/aliases.json] \\
        --out /secure/field_data

Then start the API with ``FIELD_DATA_DIR=/secure/field_data``.

Rules enforced here:
- no run without a complete, unexpired authorization that covers the
  document type and country (see docs/field-data/README.zh-CN.md);
- raw input must live outside the repository;
- the output holds only redacted text, a SHA-256 of each original for audit,
  and a redaction report with counts (never the removed values);
- a person must still review the report and a sample of records before use.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.field_data import (  # noqa: E402
    FIELD_RECORDS_FILE, AuthorizationError, fingerprint, redact, validate_authorization,
)

TEXT_SUFFIXES = {".txt", ".md", ".eml", ".csv"}


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT)
        return True
    except ValueError:
        return False


def _ignored_by_git(path: Path) -> bool:
    result = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", str(path)], check=False)
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", required=True, type=Path, help="folder of raw .txt/.md/.eml/.csv files (outside the repo)")
    parser.add_argument("--authorization", required=True, type=Path, help="authorization record (JSON)")
    parser.add_argument("--project-code", required=True)
    parser.add_argument("--country", required=True, choices=["MY", "ID", "SA", "AE"])
    parser.add_argument("--document-type", required=True, help="e.g. CORRESPONDENCE, NCR, DAILY_REPORT, VARIATION_REQUEST")
    parser.add_argument("--names", type=Path, help="one person name per line, replaced with [PERSON]")
    parser.add_argument("--aliases", type=Path, help='JSON {"Real Company Sdn Bhd": "Contractor A", ...}')
    parser.add_argument("--stage", default="construction")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    if _inside_repo(args.input):
        print("REFUSED: raw input must be stored outside the repository.", file=sys.stderr)
        return 2
    if _inside_repo(args.out) and not _ignored_by_git(args.out):
        print("REFUSED: output inside the repository must be git-ignored until a person has reviewed it.", file=sys.stderr)
        return 2
    try:
        authorization = validate_authorization(json.loads(args.authorization.read_text(encoding="utf-8")), document_type=args.document_type)
    except (AuthorizationError, json.JSONDecodeError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if args.country not in authorization["countries"]:
        print(f"REFUSED: country {args.country} is outside the authorized scope.", file=sys.stderr)
        return 2

    names = [line.strip() for line in args.names.read_text(encoding="utf-8").splitlines()] if args.names else []
    aliases = json.loads(args.aliases.read_text(encoding="utf-8")) if args.aliases else {}
    files = sorted(p for p in args.input.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES)
    if not files:
        print("No .txt/.md/.eml/.csv files found.", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    imported_at = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat()
    totals: dict[str, int] = {}
    records = []
    for index, path in enumerate(files, 1):
        original = path.read_text(encoding="utf-8", errors="replace")
        result = redact(original, names=names, aliases=aliases)
        for kind, n in result.counts.items():
            totals[kind] = totals.get(kind, 0) + n
        title = redact(path.stem.replace("_", " "), names=names, aliases=aliases).text
        record_id = f"FIELD-{authorization['authorization_id']}-{args.document_type}-{index:04d}"
        records.append({
            "record_id": record_id, "project_code": args.project_code, "country": args.country,
            "document_type": args.document_type, "title": title, "text": result.text,
            "lifecycle_stages": [args.stage], "original_sha256": fingerprint(original),
            "redacted_sha256": fingerprint(result.text), "redaction_counts": result.counts,
            "authorization": authorization, "imported_at": imported_at,
        })
    with (args.out / FIELD_RECORDS_FILE).open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    report = {
        "authorization_id": authorization["authorization_id"], "grantor_organisation": authorization["grantor_organisation"],
        "permitted_uses": authorization["permitted_uses"], "expires_on": authorization["expires_on"],
        "project_code": args.project_code, "country": args.country, "document_type": args.document_type,
        "files": len(records), "redactions": totals, "imported_at": imported_at,
        "human_review_required": "Read the report and spot-check at least 10% of records before setting FIELD_DATA_DIR.",
    }
    (args.out / "redaction_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
