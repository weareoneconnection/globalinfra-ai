#!/usr/bin/env python3
"""Country adaptation comparison for finals (configuration evidence only).

Compares official source *indexes*, configured policies, language context and
permitted activity gates for two Country Packs. It cannot certify legal
applicability or prove use in a second-country production project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def report(code_a: str, code_b: str, stage: str = "construction") -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
    from app.country_knowledge import COUNTRY_PACKS, OFFICIAL_KNOWLEDGE
    if code_a == code_b:
        raise ValueError("COUNTRIES_MUST_DIFFER")
    if code_a not in COUNTRY_PACKS or code_b not in COUNTRY_PACKS:
        raise ValueError("UNKNOWN_COUNTRY_PACK")

    def data(code: str) -> dict:
        pack = COUNTRY_PACKS[code]
        permits = [
            {"code": item["code"], "authority": item["authority"],
             "gate": item["gate"], "evidence": item["evidence"]}
            for item in pack["permits"] if stage in item["stages"]
        ]
        sources = [
            {"source_ref": row[0], "authority": row[4], "version_label": row[5],
             "source_url": row[6]}
            for row in OFFICIAL_KNOWLEDGE if row[1] == code
        ]
        return {
            "country": code, "version": pack["version"], "languages": pack["languages"],
            "timezone": pack["timezone"], "currency": pack["currency"],
            "data_policy": pack["data_policy"], "authority_codes":
                [item["code"] for item in pack["authorities"]],
            "permit_gates": permits, "source_indexes": sources,
            "review_gate": "EXPERT_REVIEW_REQUIRED",
            "status": "DEMO_CONFIG_ONLY",
        }

    first, second = data(code_a), data(code_b)
    return {
        "schema": "globalinfra.country-adaptation.v1",
        "status": "CONFIGURATION_COMPARISON_ONLY",
        "first": first, "second": second,
        "stage": stage,
        "differences": {
            "languages_changed": first["languages"] != second["languages"],
            "authorities_changed": first["authority_codes"] != second["authority_codes"],
            "permits_changed": first["permit_gates"] != second["permit_gates"],
            "data_policy_changed": first["data_policy"] != second["data_policy"],
        },
        "config_sha256": {code_a: canonical_hash(first), code_b: canonical_hash(second)},
        "boundary": (
            "Deterministic Country Pack configuration comparison; source URLs "
            "are indexes, not a verified legal analysis. No local legal review "
            "or multi-country deployment success is asserted."
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--country-a", default="MY")
    p.add_argument("--country-b", default="AE")
    p.add_argument("--stage", default="construction")
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    try:
        result = report(args.country_a.upper(), args.country_b.upper(), args.stage.lower())
    except ValueError as exc:
        print(json.dumps({"status": "NOT_RUN", "reason": str(exc)}))
        return 2
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
