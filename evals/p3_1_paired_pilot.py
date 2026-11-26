#!/usr/bin/env python3
"""P3.1 paired human-vs-AI pilot time report; source audit NOT automated.

No real ROI or financial claim can be inferred from a checksum alone.
The script computes only descriptive paired-value statistics and
bootstrap case-sampling intervals from the P1 canonical evidence payload.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
from app.roi_evidence import PairedStudy, evidence_sha256, study_means

SCHEMA = "globalinfra.p3-1.paired-pilot.v1"
MIN_PILOT_CASES = 20
MAX_PILOT_CASES = 500


def _percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("EMPTY_VALUES")
    sorted_values = sorted(values)
    ix = q * (len(sorted_values) - 1)
    a = int(ix)
    b = min(len(values) - 1, a + 1)
    return sorted_values[a] + (sorted_values[b] - sorted_values[a]) * (ix-a)


def paired_pilot_report(
    study: PairedStudy, *,
    protocol_ref: str, evidence_source_bundle_sha256: str,
    independent_reviewer_ref: str, direction: str = "LOWER",
) -> dict:
    import re
    if not re.fullmatch(r"[a-f0-9]{64}", evidence_source_bundle_sha256):
        raise ValueError("SOURCE_BUNDLE_SHA256_REQUIRED")
    if len(protocol_ref.strip()) < 6 or len(independent_reviewer_ref.strip()) < 6:
        raise ValueError("INDEPENDENT_SOURCE_AUDIT_REFERENCES_REQUIRED")
    if direction not in {"LOWER", "HIGHER"}:
        raise ValueError("UNSUPPORTED_METRIC_DIRECTION")
    n = len(study.cases)
    if not MIN_PILOT_CASES <= n <= MAX_PILOT_CASES:
        raise ValueError("PILOT_SAMPLE_SIZE_OUTSIDE_20_TO_500")
    mean_baseline, mean_assisted = study_means(study)
    if mean_baseline <= 0:
        raise ValueError("BASELINE_MUST_BE_POSITIVE")
    pairs = [(row.baseline_value, row.assisted_value) for row in study.cases]
    deltas = [((a-b) if direction == "LOWER" else (b-a)) for a,b in pairs]
    # A positive delta means an improvement. This is NOT a money estimate.
    mean_delta = math.fsum(deltas)/n
    relative = 100 * mean_delta/mean_baseline
    rng = random.Random(int(evidence_sha256(study)[:16],16))
    boot = []
    for _ in range(3000):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        base = math.fsum(row[0] for row in sample)/n
        assist = math.fsum(row[1] for row in sample)/n
        delta = base-assist if direction == "LOWER" else assist-base
        boot.append(100 * delta/base if base > 0 else math.nan)
    if any(not math.isfinite(x) for x in boot):
        raise ValueError("INVALID_BOOTSTRAP_DENOMINATOR")
    interval = [round(_percentile(boot, .025), 3), round(_percentile(boot, .975), 3)]
    source_real = study.source_type == "AUTHORIZED_REAL"
    return {
        "schema": SCHEMA,
        "status": (
            "PAIRED_DESCRIPTIVE_SOURCE_AUDIT_PENDING"
            if source_real else "SYNTHETIC_TEST_ONLY_NOT_CLAIMABLE"
        ),
        "metric": {"name": study.metric_name, "unit": study.unit, "direction": direction},
        "cases": n,
        "baseline_mean": round(mean_baseline, 3),
        "assisted_mean": round(mean_assisted, 3),
        "improvement_mean_absolute": round(mean_delta, 3),
        "improvement_percent_descriptive": round(relative, 3),
        "improvement_percent_bootstrap_case_sampling_95_ci": interval,
        "worse_cases": sum(v < 0 for v in deltas),
        "unchanged_cases": sum(v == 0 for v in deltas),
        "better_cases": sum(v > 0 for v in deltas),
        "provenance": {
            "paired_study_sha256": evidence_sha256(study),
            "source_bundle_sha256_declared_unverified": evidence_source_bundle_sha256,
            "authorization_ref": study.authorization_ref,
            "study_protocol_ref": study.study_protocol_ref,
            "pilot_protocol_ref": protocol_ref,
            "independent_reviewer_ref_declared_unverified": independent_reviewer_ref,
        },
        "economic_claim": None,
        "financial_roi": None,
        "publication_gate": "CLOSED_PENDING_RAW_TIMESHEET_AUDIT_AND_APPROVAL",
        "limitations": [
            "Original timestamps, human work logs, matching case difficulty, selection process and reviewer identity are not independently verified by this tool.",
            "Bootstrap intervals represent sampled case variation only, not randomization or causal treatment effects.",
            "No extrapolated avoided accident costs, financial ROI, company savings or productivity claim is authorized.",
            "The source bundle checksum protects submitted evidence bytes only after an auditor independently checks and signs the underlying source.",
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--paired-study", type=Path, required=True)
    p.add_argument("--protocol-ref", required=True)
    p.add_argument("--source-bundle-sha256", required=True)
    p.add_argument("--independent-reviewer-ref", required=True)
    p.add_argument("--direction", choices=["LOWER", "HIGHER"], default="LOWER")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    try:
        study = PairedStudy.model_validate_json(args.paired_study.read_bytes())
        result = paired_pilot_report(
            study, protocol_ref=args.protocol_ref,
            evidence_source_bundle_sha256=args.source_bundle_sha256,
            independent_reviewer_ref=args.independent_reviewer_ref,
            direction=args.direction,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(json.dumps({"status":"FAILED_CLOSED","reason":str(e)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
