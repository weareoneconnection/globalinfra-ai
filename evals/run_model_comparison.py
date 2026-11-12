#!/usr/bin/env python3
"""V6 rules/raw-LLM/RAG/governed comparison protocol.

This runner is intentionally fail-closed. A real blinded dataset and an
approved model configuration must be supplied by the validation team; absent
either, it emits NOT_RUN instead of turning synthetic regression scores into a
model-performance claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


GROUPS = ("rules", "raw_llm", "rag", "governed")
REQUIRED_FIELDS = {
    "id",
    "input",
    "expected_risk",
    "expected_action",
    "expected_evidence",
    "requires_abstention",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    reasons: list[str] = []
    rows: list[dict] = []
    dataset_digest = None

    if args.dataset is None or not args.dataset.is_file():
        reasons.append("BLINDED_DATASET_NOT_PROVIDED")
    else:
        dataset_digest = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
        try:
            rows = [
                json.loads(line)
                for line in args.dataset.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except json.JSONDecodeError:
            reasons.append("BLINDED_DATASET_INVALID_JSONL")
        if rows and any(not REQUIRED_FIELDS.issubset(row) for row in rows):
            reasons.append("BLINDED_DATASET_SCHEMA_INVALID")
        if len(rows) < 50:
            reasons.append("BLINDED_DATASET_BELOW_MINIMUM_50")

    provider_ready = bool(
        os.getenv("MODEL_EVAL_PROVIDER")
        and os.getenv("MODEL_EVAL_MODEL")
        and os.getenv("MODEL_EVAL_API_KEY")
    )
    if not provider_ready:
        reasons.append("APPROVED_MODEL_CONFIGURATION_NOT_PROVIDED")

    groups = [
        {
            "id": group,
            "status": "NOT_RUN" if reasons else "READY_FOR_EXTERNAL_HARNESS",
            "metrics": {},
            "runs_per_case": 3,
        }
        for group in GROUPS
    ]
    payload = {
        "schema": "globalinfra.model-comparison.v1",
        "status": "NOT_RUN" if reasons else "READY_FOR_EXTERNAL_HARNESS",
        "reasons": sorted(set(reasons)),
        "dataset": {
            "path": str(args.dataset) if args.dataset else None,
            "records": len(rows),
            "sha256": dataset_digest,
            "authorization_attested": os.getenv("DATASET_AUTHORIZATION_ATTESTED")
            == "true",
        },
        "groups": groups,
        "required_metrics": [
            "critical_risk_recall",
            "macro_f1",
            "citation_precision",
            "unsupported_confident_answer_rate",
            "correct_abstention_rate",
            "unauthorized_execution_count",
            "p50_latency_ms",
            "p95_latency_ms",
            "cost_per_case",
        ],
        "boundary": "No model-performance result exists until an authorized blinded run is completed.",
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
