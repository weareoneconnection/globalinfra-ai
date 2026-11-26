#!/usr/bin/env python3
"""Build an expert / native-speaker review packet (CSV) for the clause library.

Usage:
    python scripts/build_review_packet.py --country MY --kind clause --per-instrument 5 --out /secure/review/MY-clauses.csv
    python scripts/build_review_packet.py --country ID --kind term --sample 60 --out /secure/review/ID-terms.csv

The packet is a stratified, reproducible sample (seeded by --packet-id). The
reviewer fills in verdict / correction / comment for each row and signs the
cover sheet; scripts/import_review.py turns the filled CSV into review records.
Nothing is marked reviewed until that import runs on a real, filled packet.
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.country_knowledge import load_clause_library, load_glossary  # noqa: E402

REVIEW_COLUMNS = ["verdict", "correction", "comment"]
VERDICT_HELP = "ACCURATE | MINOR_CORRECTION | INACCURATE"


def clause_rows(country: str, per_instrument: int, rng: random.Random) -> list[dict]:
    by_instrument: dict[str, list[dict]] = defaultdict(list)
    for row in load_clause_library():
        if row["country"] == country:
            by_instrument[row["instrument"]].append(row)
    picked = []
    for instrument in sorted(by_instrument):
        rows = sorted(by_instrument[instrument], key=lambda r: r["id"])
        picked.extend(rng.sample(rows, min(per_instrument, len(rows))))
    return [{
        "item_type": "clause", "item_id": r["id"], "instrument": r["instrument"], "provision": r["provision"],
        "source_url": r["source_url"], "read_quality": r["read_quality"],
        "summary_en": r["summary"]["en"], "summary_zh": r["summary"]["zh"],
    } for r in picked]


def term_rows(country: str, sample: int, rng: random.Random) -> list[dict]:
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for row in load_glossary(country):
        by_domain[row["domain"]].append(row)
    total = sum(len(v) for v in by_domain.values())
    picked = []
    for domain in sorted(by_domain):
        rows = sorted(by_domain[domain], key=lambda r: r["id"])
        quota = max(1, round(sample * len(rows) / total)) if total else 0
        picked.extend(rng.sample(rows, min(quota, len(rows))))
    return [{
        "item_type": "term", "item_id": r["id"], "domain": r["domain"], "en": r["en"], "zh": r["zh"],
        "local": r["local"], "local_lang": r["local_lang"], "local_basis": r["local_basis"],
    } for r in picked]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--country", required=True, choices=["MY", "ID"])
    parser.add_argument("--kind", required=True, choices=["clause", "term"])
    parser.add_argument("--per-instrument", type=int, default=5, help="clauses sampled per instrument")
    parser.add_argument("--sample", type=int, default=60, help="glossary terms sampled (stratified by domain)")
    parser.add_argument("--packet-id", help="defaults to <country>-<kind>-<date>")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    packet_id = args.packet_id or f"{args.country}-{args.kind.upper()}-{date.today().isoformat()}"
    rng = random.Random(packet_id)
    rows = clause_rows(args.country, args.per_instrument, rng) if args.kind == "clause" else term_rows(args.country, args.sample, rng)
    if not rows:
        print("Nothing to sample.", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["packet_id", *rows[0].keys(), *REVIEW_COLUMNS])
        writer.writeheader()
        for row in rows:
            writer.writerow({"packet_id": packet_id, **row, "verdict": "", "correction": "", "comment": ""})
    print(f"{packet_id}: {len(rows)} rows -> {args.out}  (verdict: {VERDICT_HELP})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
