#!/usr/bin/env python3
"""P3.1 prospective four-arm blind-study evidence gate.

This tool NEVER awards a public/production claim. Its highest possible state
is EXPERT_ADJUDICATED_SOURCE_AUDIT_PENDING. The operator must independently
verify consent, reviewer independence, underlying evidence and publication
authorization before releasing any results. No dataset or secret is uploaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import secrets
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

# Support `python evals/p3_1_study.py` as well as pytest module imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.run_model_comparison import GROUPS, ALLOWED_RISKS, digest, validate_dataset

STUDY_SCHEMA = "globalinfra.p3-1.study.v1"
BLIND_SCHEMA = "globalinfra.p3-1.blind.v1"
KEY_SCHEMA = "globalinfra.p3-1.blind-key.v1"
ROSTER_SCHEMA = "globalinfra.p3-1.roster.v1"
REPORT_SCHEMA = "globalinfra.p3-1.expert-report.v1"
PREDICTION_FIELDS = ("action_appropriate", "citation_supported",
                     "abstention_appropriate", "unsafe_recommendation")
GOLD_FIELDS = ("risk", "requires_abstention")


def canonical(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def file_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("EXPECTED_JSON_OBJECT")
    return data


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")


def freeze(
    dataset: Path, *, protocol_id: str, authorization_ref: str,
    attested_by: str, model_id: str, provider_host: str,
    governed_host: str, source_commit: str,
) -> dict:
    rows, problems, sha = validate_dataset(dataset)
    if problems:
        raise ValueError("DATASET_INVALID:" + ",".join(problems))
    norm = [" ".join(r["input"].lower().split()) for r in rows]
    if len(set(norm)) != len(norm):
        raise ValueError("DUPLICATED_CASE_TEXT")
    if sum(r["expected_risk"] == "CRITICAL" for r in rows) < 5:
        raise ValueError("CRITICAL_STRATUM_BELOW_FIVE")
    if sum(r["requires_abstention"] for r in rows) < 5:
        raise ValueError("ABSTENTION_STRATUM_BELOW_FIVE")
    for name, value in (("protocol_id", protocol_id),
                        ("authorization_ref", authorization_ref),
                        ("attested_by", attested_by),
                        ("model_id", model_id), ("source_commit", source_commit)):
        if not value or len(value.strip()) < 6:
            raise ValueError("MISSING_PROTOCOL_FIELD:" + name)
    hosts = {}
    for label, host in (("provider", provider_host), ("governed", governed_host)):
        if host != host.lower() or "/" in host or "@" in host or ":" in host:
            raise ValueError("INVALID_APPROVED_HOST:" + label)
        parsed = urlparse("https://" + host)
        if not parsed.hostname or parsed.hostname != host:
            raise ValueError("INVALID_APPROVED_HOST:" + label)
        hosts[label] = host
    if hosts["provider"] == hosts["governed"]:
        raise ValueError("SEPARATE_PROVIDER_AND_GOVERNED_HOSTS_REQUIRED")
    languages = Counter(str(row.get("language", "unspecified")) for row in rows)
    return {
        "schema": STUDY_SCHEMA,
        "status": "FROZEN_DECLARED_AUTHORIZATION_UNVERIFIED",
        "protocol_id": protocol_id,
        "dataset": {
            "sha256": sha, "cases": len(rows),
            "critical_cases": sum(r["expected_risk"] == "CRITICAL" for r in rows),
            "abstention_cases": sum(r["requires_abstention"] for r in rows),
            "languages": dict(sorted(languages.items())),
            "source_classification": "PUBLIC_ONLY",
        },
        "authorization": {
            "reference": authorization_ref, "attested_by": attested_by,
            "verified_independently": False,
        },
        "execution": {
            "model_id": model_id, "approved_hosts": hosts,
            "source_commit": source_commit, "arms": list(GROUPS),
            "repetitions": 1, "temperature_policy": "PROVIDER_DEFAULT_RECORDED",
        },
        "review": {
            "minimum_independent_reviewers_per_item": 2,
            "separate_adjudicator_required_for_disagreements": True,
            "gold_labels_require_independent_review": True,
        },
        "publication_gate": "CLOSED",
        "boundary": "A declared authorization and dataset checksum are NOT an "
                    "independent verification of permission, expert labels or accuracy.",
    }


def validate_freeze(frozen: dict, dataset: Path) -> list[dict]:
    if frozen.get("schema") != STUDY_SCHEMA or frozen.get("publication_gate") != "CLOSED":
        raise ValueError("INVALID_STUDY_MANIFEST")
    rows, errors, sha = validate_dataset(dataset)
    if errors or sha != frozen["dataset"]["sha256"]:
        raise ValueError("DATASET_CHANGED_AFTER_FREEZE:" + ",".join(errors))
    if len(rows) != frozen["dataset"]["cases"]:
        raise ValueError("DATASET_CASE_COUNT_CHANGED")
    return rows


def _read_raw(frozen: dict, dataset: Path, comparison: Path,
              raw_dir: Path) -> tuple[list[dict], dict, dict[str, list[dict]], dict]:
    rows = validate_freeze(frozen, dataset)
    result = file_json(comparison)
    if result.get("status") != "EXECUTED_UNREVIEWED":
        raise ValueError("REAL_FOUR_ARM_EXECUTION_NOT_COMPLETE")
    if result.get("dataset", {}).get("sha256") != frozen["dataset"]["sha256"]:
        raise ValueError("COMPARISON_DATASET_HASH_MISMATCH")
    if result.get("frozen_study_sha256") != digest(canonical(frozen)):
        raise ValueError("COMPARISON_STUDY_HASH_MISMATCH")
    if {x.get("id") for x in result.get("groups", [])} != set(GROUPS):
        raise ValueError("FOUR_ARM_SET_INCOMPLETE")
    if any(x.get("status") != "EXECUTED_UNREVIEWED" for x in result["groups"]):
        raise ValueError("ARM_NOT_COMPLETED")
    expected_ids = {x["id"] for x in rows}
    outputs: dict[str, list[dict]] = {}
    hashes = {}
    for arm in GROUPS:
        path = raw_dir / f"{arm}.json"
        raw = path.read_bytes()
        sha = digest(raw)
        if sha != result.get("raw_output_sha256", {}).get(arm):
            raise ValueError("RAW_OUTPUT_DIGEST_MISMATCH:" + arm)
        predictions = json.loads(raw)
        if not isinstance(predictions, list) or len(predictions) != len(rows):
            raise ValueError("RAW_OUTPUT_COUNT_MISMATCH:" + arm)
        ids = [x["id"] for x in predictions]
        if len(set(ids)) != len(ids) or set(ids) != expected_ids:
            raise ValueError("RAW_OUTPUT_IDS_MISMATCH:" + arm)
        if any(x.get("arm") != arm or x.get("risk") not in ALLOWED_RISKS
               or not isinstance(x.get("evidence_refs"), list)
               for x in predictions):
            raise ValueError("RAW_OUTPUT_SCHEMA_INVALID:" + arm)
        outputs[arm] = predictions
        hashes[arm] = sha
    return rows, result, outputs, hashes


def blind_packet(frozen: dict, dataset: Path, comparison: Path,
                 raw_dir: Path) -> tuple[dict, dict]:
    rows, result, outputs, hashes = _read_raw(frozen, dataset, comparison, raw_dir)
    by_arm = {arm: {r["id"]: r for r in predictions}
              for arm, predictions in outputs.items()}
    packet_cases: list[dict] = []
    key_cases: dict[str, dict] = {}
    shuffle = secrets.SystemRandom()
    for row in rows:
        arms = list(GROUPS)
        shuffle.shuffle(arms)
        key_cases[row["id"]] = {alias: arm for alias, arm in zip("ABCD", arms)}
        candidates = []
        for alias in "ABCD":
            pred = by_arm[key_cases[row["id"]][alias]][row["id"]]
            candidates.append({
                "alias": alias, "risk": pred["risk"],
                "action": pred["action"],
                "evidence_refs": pred["evidence_refs"],
                "abstained": pred["abstained"],
            })
        packet_cases.append({
            "case_id": row["id"], "notice": row["input"],
            "evidence_context": row.get("evidence_context", []),
            "candidates": candidates,
        })
    packet = {
        "schema": BLIND_SCHEMA,
        "status": "AWAITING_EXPERT_REVIEW",
        "protocol_id": frozen["protocol_id"],
        "dataset_sha256": frozen["dataset"]["sha256"],
        "comparison_sha256": digest(comparison.read_bytes()),
        "cases": packet_cases,
        "review_instructions": (
            "Review GOLD independently without seeing dataset expected labels. "
            "Review every A/B/C/D candidate without knowing its arm. "
            "Record two different reviewers per case and candidate, with "
            "adjudicator only on disagreement. Keep packet and notice text private."
        ),
    }
    key = {
        "schema": KEY_SCHEMA,
        "protocol_id": frozen["protocol_id"],
        "dataset_sha256": frozen["dataset"]["sha256"],
        "comparison_sha256": packet["comparison_sha256"],
        "packet_sha256": digest(canonical(packet)),
        "raw_output_sha256": hashes,
        "aliases": key_cases,
        "boundary": "RESTRICTED_INTERNAL_ONLY_DO_NOT_SHARE_WITH_BLINDED_REVIEWERS",
    }
    return packet, key


def roster_roles(roster: dict) -> tuple[set[str], str]:
    if roster.get("schema") != ROSTER_SCHEMA:
        raise ValueError("INVALID_ROSTER_SCHEMA")
    reviewers = roster.get("reviewers", [])
    if not isinstance(reviewers, list) or len(reviewers) < 3:
        raise ValueError("MINIMUM_THREE_EXPERTS_REQUIRED")
    ids = [x.get("id") for x in reviewers]
    if any(not isinstance(x, str) or len(x) < 3 for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("DUPLICATE_OR_INVALID_REVIEWER_ID")
    for item in reviewers:
        if item.get("specialty") not in {"engineering", "hse", "contracts", "local_law", "quality"}:
            raise ValueError("UNDECLARED_EXPERT_SPECIALTY")
    adjudicators = [x["id"] for x in reviewers if x.get("role") == "adjudicator"]
    normal = {x["id"] for x in reviewers if x.get("role") == "reviewer"}
    if len(adjudicators) != 1 or len(normal) < 2 or len(normal) + 1 != len(ids):
        raise ValueError("TWO_REVIEWERS_AND_DISTINCT_ADJUDICATOR_REQUIRED")
    if roster.get("independence_attested") is not True:
        raise ValueError("REVIEWER_INDEPENDENCE_NOT_ATTESTED")
    return normal, adjudicators[0]


def reviewer_consensus(
    evaluations: list[dict], normal: set[str], adjudicator: str,
    fields: tuple[str, ...], key: str,
) -> tuple[dict | None, str]:
    base = [r for r in evaluations if r["reviewer_id"] in normal]
    tie = [r for r in evaluations if r["reviewer_id"] == adjudicator]
    if len(base) != 2 or len({r["reviewer_id"] for r in base}) != 2:
        return None, "INCOMPLETE_INDEPENDENT_REVIEW:" + key
    if len(tie) > 1:
        return None, "DUPLICATED_ADJUDICATOR_REVIEW:" + key
    if all(base[0][f] == base[1][f] for f in fields):
        if tie:
            return None, "UNSOLICITED_ADJUDICATION:" + key
        return {f: base[0][f] for f in fields}, ""
    if not tie:
        return None, "ADJUDICATION_REQUIRED:" + key
    return {f: tie[0][f] for f in fields}, ""


def wilson(successes: int, n: int) -> list[float] | None:
    if n == 0:
        return None
    z = 1.959963984540054
    p = successes / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt((p * (1 - p) / n) + z * z / (4 * n * n)) / den
    return [round(max(0, center-half), 4), round(min(1, center+half), 4)]


def paired_effect(rows: list[dict], a: dict, b: dict, sha: str) -> dict:
    """Paired risk-accuracy difference with deterministic percentile bootstrap."""
    # Align by case ID, never by model response order.
    scores = [(int(a[row["id"]]["risk"] == row["expected_risk"]),
               int(b[row["id"]]["risk"] == row["expected_risk"]))
              for row in rows]
    delta = sum(x-y for x, y in scores)/len(scores)
    wins = sum(x==1 and y==0 for x,y in scores)
    losses = sum(x==0 and y==1 for x,y in scores)
    discordant = wins + losses
    p_two = min(1.0, (2 * sum(math.comb(discordant, i) for i in
                                range(min(wins, losses)+1)) / (2 ** discordant))) if discordant else 1.0
    rng = random.Random(int(sha[:16], 16))
    boot = []
    for _ in range(2000):
        sample = [scores[rng.randrange(len(scores))] for _ in scores]
        boot.append(sum(x-y for x,y in sample)/len(sample))
    boot.sort()
    return {
        "delta_risk_accuracy": round(delta, 4),
        "bootstrap_95_ci": [round(boot[49], 4), round(boot[1950], 4)],
        "paired_wins": wins, "paired_losses": losses,
        "discordant": discordant, "exact_sign_test_two_sided_p": round(p_two, 6),
        "interpretation": "Descriptive paired comparison; external study design/label review required.",
    }


def _grade_arm(rows: list[dict], preds: dict, expert: dict) -> dict:
    count = len(rows)
    matches = sum(preds[row["id"]]["risk"] == row["expected_risk"] for row in rows)
    critical = [r for r in rows if r["expected_risk"] == "CRITICAL"]
    critical_hits = sum(preds[r["id"]]["risk"] == "CRITICAL" for r in critical)
    def rate(field: str) -> float:
        return round(sum(expert[(r["id"], preds[r["id"]]["alias"])][field]
                         for r in rows) / count, 4)
    cited = [(r, ref) for r in rows for ref in preds[r["id"]]["evidence_refs"]]
    good = sum(ref in r["expected_evidence"] for r,ref in cited)
    required = [r for r in rows if r["expected_evidence"] and not preds[r["id"]]["abstained"]]
    missing = sum(not preds[r["id"]]["evidence_refs"] for r in required)
    unsafe = sum(expert[(r["id"], preds[r["id"]]["alias"])]["unsafe_recommendation"]
                 for r in rows)
    return {
        "cases": count,
        "risk_accuracy": round(matches / count, 4),
        "risk_accuracy_wilson_95_ci": wilson(matches, count),
        "critical_risk_recall": round(critical_hits / len(critical), 4) if critical else None,
        "critical_recall_wilson_95_ci": wilson(critical_hits, len(critical)),
        "action_appropriate_expert_rate": rate("action_appropriate"),
        "citation_supported_expert_rate": rate("citation_supported"),
        "abstention_appropriate_expert_rate": rate("abstention_appropriate"),
        "citation_precision_against_gold_refs": round(good/len(cited), 4) if cited else None,
        "missing_citation_rate_when_expected": round(missing/len(required), 4) if required else None,
        "unsafe_recommendations": unsafe,
        "unauthorized_external_actions": sum(bool(preds[r["id"]].get("external_action_executed")) for r in rows),
        "cost_per_case": None,
    }


def adjudicate(frozen: dict, dataset: Path, comparison: Path,
               raw_dir: Path, packet: dict, key: dict,
               roster: dict, reviews: list[dict]) -> dict:
    rows, result, raw, hashes = _read_raw(frozen, dataset, comparison, raw_dir)
    normal, adjudicator = roster_roles(roster)
    if packet.get("schema") != BLIND_SCHEMA or key.get("schema") != KEY_SCHEMA:
        raise ValueError("BLIND_PACKET_OR_KEY_SCHEMA_INVALID")
    if key.get("packet_sha256") != digest(canonical(packet)):
        raise ValueError("BLIND_PACKET_TAMPERED")
    if packet["dataset_sha256"] != frozen["dataset"]["sha256"]:
        raise ValueError("BLIND_DATASET_MISMATCH")
    if key["comparison_sha256"] != digest(comparison.read_bytes()):
        raise ValueError("BLIND_COMPARISON_MISMATCH")
    if key["raw_output_sha256"] != hashes:
        raise ValueError("BLIND_RAW_EVIDENCE_MISMATCH")
    ids = {r["id"] for r in rows}
    aliases = key.get("aliases", {})
    if (set(aliases) != ids or len(packet.get("cases", [])) != len(rows)
            or len({c.get("case_id") for c in packet["cases"]}) != len(rows)):
        raise ValueError("BLIND_CASE_IDS_MISMATCH")
    by_arm = {arm: {x["id"]: x for x in values} for arm, values in raw.items()}
    for row in rows:
        mapping = aliases[row["id"]]
        if set(mapping) != set("ABCD") or set(mapping.values()) != set(GROUPS):
            raise ValueError("BLIND_ALIAS_MAPPING_INVALID")
        case = next((x for x in packet["cases"] if x.get("case_id") == row["id"]), None)
        if case is None or case.get("notice") != row["input"]:
            raise ValueError("BLIND_CASE_CONTENT_MISMATCH")
        if case.get("evidence_context") != row.get("evidence_context", []):
            raise ValueError("BLIND_REFERENCE_CONTENT_MISMATCH")
        if (len(case.get("candidates", [])) != len(GROUPS)
                or {candidate.get("alias") for candidate in case["candidates"]} != set("ABCD")):
            raise ValueError("BLIND_PREDICTION_COUNT_INVALID")
        for item in case["candidates"]:
            arm = mapping.get(item.get("alias"))
            if arm is None:
                raise ValueError("BLIND_UNKNOWN_ALIAS")
            source = by_arm[arm][row["id"]]
            if any(item.get(field) != source.get(field)
                   for field in ("risk", "action", "evidence_refs", "abstained")):
                raise ValueError("BLIND_RESPONSE_TAMPERED")
    grouped = defaultdict(list)
    for item in reviews:
        if not isinstance(item, dict):
            raise ValueError("REVIEW_ROW_INVALID")
        kind, case_id, reviewer = item.get("kind"), item.get("case_id"), item.get("reviewer_id")
        if case_id not in ids or reviewer not in (normal | {adjudicator}):
            raise ValueError("REVIEW_CASE_OR_REVIEWER_UNRECOGNIZED")
        if kind == "gold":
            if item.get("risk") not in ALLOWED_RISKS or type(item.get("requires_abstention")) is not bool:
                raise ValueError("GOLD_REVIEW_SCHEMA_INVALID")
            group_key = ("gold", case_id)
        elif kind == "prediction":
            alias = item.get("alias")
            if not isinstance(alias, str) or alias not in ("A", "B", "C", "D"):
                raise ValueError("PREDICTION_REVIEW_ALIAS_INVALID")
            if any(type(item.get(field)) is not bool for field in PREDICTION_FIELDS):
                raise ValueError("PREDICTION_REVIEW_SCHEMA_INVALID")
            group_key = ("prediction", case_id, alias)
        else:
            raise ValueError("REVIEW_KIND_INVALID")
        grouped[group_key].append(item)
    expected_keys = {("gold", x) for x in ids} | {
        ("prediction", x, alias) for x in ids for alias in "ABCD"}
    if set(grouped) - expected_keys:
        raise ValueError("UNEXPECTED_REVIEW_ENTRIES")
    gold = {}
    expert = {}
    issues = []
    for row in rows:
        cid = row["id"]
        answer, problem = reviewer_consensus(grouped[("gold", cid)], normal, adjudicator, GOLD_FIELDS, "gold:" + cid)
        if problem:
            issues.append(problem)
        elif answer["risk"] != row["expected_risk"] or answer["requires_abstention"] != row["requires_abstention"]:
            issues.append("EXPERT_GOLD_DIFFERS_FROM_FROZEN_LABEL:" + cid)
        else:
            gold[cid] = answer
        for alias in "ABCD":
            result_vote, problem = reviewer_consensus(grouped[("prediction", cid, alias)], normal,
                                                      adjudicator, PREDICTION_FIELDS, cid + ":" + alias)
            if problem:
                issues.append(problem)
            else:
                expert[(cid, alias)] = result_vote
    review_hash = digest(canonical(reviews))
    report = {
        "schema": REPORT_SCHEMA,
        "status": "EXPERT_ADJUDICATED_SOURCE_AUDIT_PENDING" if not issues else "REVIEW_INCOMPLETE_OR_CONFLICTED",
        "protocol_id": frozen["protocol_id"],
        "provenance": {
            "source_commit": frozen["execution"]["source_commit"],
            "dataset_sha256": frozen["dataset"]["sha256"],
            "frozen_manifest_sha256": digest(canonical(frozen)),
            "comparison_sha256": digest(comparison.read_bytes()),
            "blind_packet_sha256": digest(canonical(packet)),
            "blind_key_sha256": digest(canonical(key)),
            "review_roster_sha256": digest(canonical(roster)),
            "review_records_sha256": review_hash,
            "raw_output_sha256": hashes,
        },
        "review": {"cases": len(rows), "reviewers": len(normal),
                   "separate_adjudicator": True,
                   "expert_gold_reviewed": len(gold),
                   "expert_candidate_reviews": len(expert),
                   "expected_candidate_reviews": len(rows) * len(GROUPS),
                   "issues": issues[:200]},
        "arms": [],
        "paired_comparisons": {},
        "publication_gate": "CLOSED_PENDING_SOURCE_AUDIT_AND_APPROVAL",
        "limitations": [
            "Reviewer identity, expertise, authorization and source truth are declarations requiring external audit.",
            "No raw case text, model output, reviewer identity or sensitive customer content is published by this summary.",
            "Execution and expert review do not establish real financial ROI or independent production adoption.",
            "The model calls run once per case; confidence intervals do not capture stochastic model variability.",
            "This report has hashes, not a protected-environment signature; publication requires separate signed approval.",
        ],
    }
    if issues:
        return report
    for arm in GROUPS:
        pred = {}
        for row in rows:
            cid = row["id"]
            alias = next(alias for alias, mapped in key["aliases"][cid].items() if mapped == arm)
            pred[cid] = {**by_arm[arm][cid], "alias": alias}
        report["arms"].append({"id": arm, "metrics": _grade_arm(rows, pred, expert)})
    for other in ("rules", "raw_llm", "rag"):
        report["paired_comparisons"]["governed_vs_" + other] = paired_effect(
            rows, by_arm["governed"], by_arm[other], frozen["dataset"]["sha256"],
        )
    return report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    f = sub.add_parser("freeze")
    for name in ("protocol-id", "authorization-ref", "attested-by", "model-id",
                 "provider-host", "governed-host", "source-commit"):
        f.add_argument("--" + name, required=True)
    f.add_argument("--dataset", type=Path, required=True)
    f.add_argument("--output", type=Path, required=True)
    b = sub.add_parser("blind")
    for name in ("dataset", "manifest", "comparison", "raw-dir", "packet", "key"):
        b.add_argument("--" + name, type=Path, required=True)
    a = sub.add_parser("adjudicate")
    for name in ("dataset", "manifest", "comparison", "raw-dir", "packet", "key",
                 "roster", "reviews", "output"):
        a.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    try:
        if args.command == "freeze":
            data = freeze(args.dataset, protocol_id=args.protocol_id,
                          authorization_ref=args.authorization_ref,
                          attested_by=args.attested_by, model_id=args.model_id,
                          provider_host=args.provider_host,
                          governed_host=args.governed_host,
                          source_commit=args.source_commit)
            write_json(args.output, data)
        elif args.command == "blind":
            packet, key = blind_packet(file_json(args.manifest), args.dataset,
                                       args.comparison, args.raw_dir)
            if args.packet.resolve() == args.key.resolve():
                raise ValueError("BLIND_KEY_MUST_BE_SEPARATE_FILE")
            write_json(args.packet, packet)
            write_json(args.key, key)
        else:
            records = [json.loads(line) for line in args.reviews.read_text(encoding="utf-8").splitlines() if line.strip()]
            data = adjudicate(file_json(args.manifest), args.dataset,
                              args.comparison, args.raw_dir,
                              file_json(args.packet), file_json(args.key),
                              file_json(args.roster), records)
            write_json(args.output, data)
            if data["status"] != "EXPERT_ADJUDICATED_SOURCE_AUDIT_PENDING":
                return 2
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "reason": str(exc)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
