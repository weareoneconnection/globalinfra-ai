#!/usr/bin/env python3
"""P1 blinded comparison executor: Rules / Raw LLM / RAG / Governed API.

Usage (credentials are only env vars; never persist in reports):
  python evals/run_model_comparison.py --output comparison.json
      -> NOT_RUN (safe default, used in release CI)
  DATASET_AUTHORIZATION_ATTESTED=true python evals/run_model_comparison.py \
      --dataset authorized_public_blind.jsonl --execute --output comparison.json

Real execution requires MODEL_EVAL_API_BASE, MODEL_EVAL_MODEL,
MODEL_EVAL_API_KEY, and MODEL_EVAL_GOVERNED_URL. The governed endpoint MUST
be the actual authenticated GlobalInfra governed-case adapter, not a
prompt posing as an enterprise governed workflow. A standalone adapter can
return the standardized prediction below and record its audit receipt.
This script never upgrades mock/fixture output to a model-performance score.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

GROUPS = ("rules", "raw_llm", "rag", "governed")
REQUIRED_FIELDS = {
    "id", "input", "expected_risk", "expected_action",
    "expected_evidence", "requires_abstention", "data_classification",
}
ALLOWED_RISKS = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
SCHEMA = "globalinfra.model-comparison.v2"
METRICS = (
    "critical_risk_recall", "macro_f1", "citation_precision",
    "unsupported_confident_answer_rate", "correct_abstention_rate",
    "unauthorized_execution_count", "p50_latency_ms", "p95_latency_ms",
    "cost_per_case",
)

def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def is_approved_endpoint(url: str, allow_local: bool) -> bool:
    p = urlparse(url)
    return (
        (p.scheme == "https" and bool(p.hostname) and not p.username and not p.password)
        or (
            allow_local and p.scheme == "http"
            and p.hostname in {"localhost", "127.0.0.1", "::1"}
        )
    )

def validate_dataset(path: Path | None) -> tuple[list[dict], list[str], str | None]:
    reasons: list[str] = []
    rows: list[dict] = []
    data_hash = None
    if not path or not path.is_file():
        return [], ["BLINDED_DATASET_NOT_PROVIDED"], None
    raw = path.read_bytes()
    data_hash = digest(raw)
    try:
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [], ["BLINDED_DATASET_INVALID_JSONL"], data_hash
    if len(rows) < 50:
        reasons.append("BLINDED_DATASET_BELOW_MINIMUM_50")
    if any(not isinstance(row, dict) or not REQUIRED_FIELDS.issubset(row) for row in rows):
        reasons.append("BLINDED_DATASET_SCHEMA_INVALID")
        return rows, reasons, data_hash
    ids = [row["id"] for row in rows]
    if any(not isinstance(k, str) or not k.strip() for k in ids) or len(ids) != len(set(ids)):
        reasons.append("DUPLICATE_OR_INVALID_CASE_IDS")
    for row in rows:
        if row["expected_risk"] not in ALLOWED_RISKS:
            reasons.append("INVALID_EXPECTED_RISK")
        if not isinstance(row["input"], str) or not row["input"].strip():
            reasons.append("INVALID_CASE_INPUT")
        if row["data_classification"] not in {"public", "internal", "restricted"}:
            reasons.append("INVALID_DATA_CLASSIFICATION")
        if not isinstance(row["expected_evidence"], list) or not all(
            isinstance(ref, str) for ref in row["expected_evidence"]
        ):
            reasons.append("INVALID_EXPECTED_EVIDENCE")
        if not isinstance(row["expected_action"], str) or not isinstance(row["requires_abstention"], bool):
            reasons.append("INVALID_REFERENCE_LABELS")
        snippets = row.get("evidence_context", [])
        if not isinstance(snippets, list) or any(
            not isinstance(x, dict) or
            not isinstance(x.get("ref"), str) or
            not isinstance(x.get("text"), str) for x in snippets
        ):
            reasons.append("INVALID_EVIDENCE_CONTEXT")
    return rows, sorted(set(reasons)), data_hash

def percentile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    ordered = sorted(xs)
    at = (len(ordered) - 1) * q
    low = int(at)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (at - low), 2)

def grade(rows: list[dict], predictions: list[dict]) -> dict:
    """Independent deterministic metric computation, no LLM judge."""
    expected = {row["id"]: row for row in rows}
    received = {row["id"]: row for row in predictions}
    if len(received) != len(rows) or set(received) != set(expected):
        raise ValueError("PREDICTION_SET_INCOMPLETE")
    risk_labels = sorted(ALLOWED_RISKS)
    f1s: list[float] = []
    for label in risk_labels:
        tp = sum(received[k].get("risk") == label and v["expected_risk"] == label for k, v in expected.items())
        fp = sum(received[k].get("risk") == label and v["expected_risk"] != label for k, v in expected.items())
        fn = sum(received[k].get("risk") != label and v["expected_risk"] == label for k, v in expected.items())
        f1s.append((2 * tp / (2 * tp + fp + fn)) if (2 * tp + fp + fn) else 0.0)
    critical = [v for v in expected.values() if v["expected_risk"] == "CRITICAL"]
    cited = [(k, ref) for k, v in received.items() for ref in v.get("evidence_refs", [])]
    supported = sum(ref in set(expected[k]["expected_evidence"]) for k, ref in cited)
    should_abstain = [k for k, v in expected.items() if v["requires_abstention"]]
    confident_unsupported = sum(
        not received[k].get("abstained", False) and not set(received[k].get("evidence_refs", [])).issubset(set(v["expected_evidence"]))
        for k, v in expected.items()
    )
    return {
        "critical_risk_recall": round(sum(received[v["id"]].get("risk") == "CRITICAL" for v in critical) / len(critical), 4) if critical else None,
        "macro_f1": round(sum(f1s) / len(f1s), 4),
        "citation_precision": round(supported / len(cited), 4) if cited else None,
        "unsupported_confident_answer_rate": round(confident_unsupported / len(rows), 4),
        "correct_abstention_rate": round(sum(bool(received[k].get("abstained")) for k in should_abstain) / len(should_abstain), 4) if should_abstain else None,
        "unauthorized_execution_count": sum(bool(v.get("external_action_executed")) for v in received.values()),
        "p50_latency_ms": percentile([v["latency_ms"] for v in received.values()], .5),
        "p95_latency_ms": percentile([v["latency_ms"] for v in received.values()], .95),
        "cost_per_case": None,  # Usage-based billing must be independently sourced.
        "evaluated_cases": len(rows),
        "note": "Lexical action correctness requires expert assessment; not inferred from risk F1.",
    }

def normalized_prediction(case_id: str, reply: dict, elapsed_ms: float, arm: str) -> dict:
    allowed = {"id", "risk", "action", "evidence_refs", "abstained", "external_action_executed"}
    if not isinstance(reply, dict) or not {"risk", "action", "evidence_refs", "abstained"}.issubset(reply):
        raise ValueError("INVALID_PREDICTION_SCHEMA")
    if reply["risk"] not in ALLOWED_RISKS:
        raise ValueError("INVALID_PREDICTION_RISK")
    if not isinstance(reply["action"], str) or not isinstance(reply["evidence_refs"], list) or not all(isinstance(r, str) for r in reply["evidence_refs"]):
        raise ValueError("INVALID_PREDICTION_FIELDS")
    if type(reply["abstained"]) is not bool or type(reply.get("external_action_executed", False)) is not bool:
        raise ValueError("INVALID_PREDICTION_BOOLEAN")
    return {
        "id": case_id, "arm": arm, "risk": reply["risk"],
        "action": reply["action"], "evidence_refs": reply["evidence_refs"],
        "abstained": reply["abstained"],
        "external_action_executed": reply.get("external_action_executed", False),
        "latency_ms": round(elapsed_ms, 2),
        "raw_response_sha256": digest(json.dumps(reply, sort_keys=True).encode()),
    }

def rules_prediction(row: dict) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
    from app.classify import classify_text
    label = classify_text(row["input"])
    # No knowledge source: rules cannot claim a source citation.
    return {"risk": label["risk"], "action": "TRIAGE_ONLY",
            "evidence_refs": [], "abstained": True, "external_action_executed": False}

def call_model(client: httpx.Client, url: str, key: str, model: str, row: dict, use_retrieval: bool) -> dict:
    references = row.get("evidence_context", []) if use_retrieval else []
    context = "\n".join(f'[{x["ref"]}] {x["text"]}' for x in references)[:12000]
    instruction = (
        "You are evaluating an overseas infrastructure notice. Return ONLY a JSON object "
        'with keys "risk" (CRITICAL/HIGH/MEDIUM/LOW), "action" (string), '
        '"evidence_refs" (array of IDs), and "abstained" (boolean). '
        "Never execute external actions. If evidence is insufficient, abstain. "
        + ("Cite only supplied source IDs: " + context if use_retrieval else "No evidence sources are available; never invent citations.")
    )
    response = client.post(
        url, headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": row["input"]},
        ]},
    )
    response.raise_for_status()
    body = response.json()
    answer = body["choices"][0]["message"]["content"]
    if not isinstance(answer, str):
        raise ValueError("MODEL_EMPTY_RESPONSE")
    answer = answer.strip()
    if answer.startswith("```"):
        answer = answer.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return json.loads(answer)

def call_governed(client: httpx.Client, url: str, key: str, row: dict) -> dict:
    """Full-system adapter; must be backed by actual governed-case runtime."""
    response = client.post(
        url, headers={"Authorization": f"Bearer {key}"},
        json={"schema": "globalinfra.blinded-governed-request.v1", "case_id": row["id"],
              "input": row["input"], "evidence_context": row.get("evidence_context", []),
              "data_classification": row["data_classification"], "external_actions_allowed": False},
    )
    response.raise_for_status()
    result = response.json()
    if result.get("schema") != "globalinfra.blinded-governed-response.v1" or not result.get("run_id"):
        raise ValueError("GOVERNED_RUNTIME_RECEIPT_REQUIRED")
    # The adapter must return the real source-bound prediction and run identity.
    return result["prediction"]

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--raw-output-dir", type=Path)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--allow-local-http", action="store_true")
    args = p.parse_args()
    rows, reasons, dataset_sha = validate_dataset(args.dataset)
    base = os.getenv("MODEL_EVAL_API_BASE", "").rstrip("/")
    model = os.getenv("MODEL_EVAL_MODEL", "")
    key = os.getenv("MODEL_EVAL_API_KEY", "")
    governed_url = os.getenv("MODEL_EVAL_GOVERNED_URL", "")
    if os.getenv("DATASET_AUTHORIZATION_ATTESTED") != "true":
        reasons.append("DATASET_AUTHORIZATION_NOT_ATTESTED")
    if any(row.get("data_classification") != "public" for row in rows):
        # No customer/private data is ever exported by this public comparison.
        reasons.append("NONPUBLIC_DATA_BLOCKED")
    if not (base and model and key and governed_url):
        reasons.append("APPROVED_MODEL_AND_GOVERNED_ADAPTER_NOT_CONFIGURED")
    elif not (
        is_approved_endpoint(base, args.allow_local_http) and
        is_approved_endpoint(governed_url, args.allow_local_http)
    ):
        reasons.append("UNAPPROVED_MODEL_OR_ADAPTER_ENDPOINT")
    reasons = sorted(set(reasons))
    result = {
        "schema": SCHEMA, "status": "NOT_RUN",
        "reasons": reasons if reasons else ([] if args.execute else ["EXECUTION_NOT_REQUESTED"]),
        "dataset": {"path": str(args.dataset) if args.dataset else None, "records": len(rows),
                    "sha256": dataset_sha, "authorization_attested":
                    os.getenv("DATASET_AUTHORIZATION_ATTESTED") == "true"},
        "groups": [{"id": arm, "status": "NOT_RUN", "metrics": {}, "runs_per_case": 1}
                   for arm in GROUPS],
        "required_metrics": list(METRICS),
        "boundary": (
            "Runs use authorized PUBLIC blind data only. Rules is the actual code classifier, "
            "raw and RAG are live OpenAI-compatible calls, and governed requires an actual "
            "run-identified GlobalInfra API adapter. No mock results are model evidence. "
            "Labels, citations and source authorization still require independent reviewers."
        ),
    }
    if args.execute and not reasons:
        results_by_arm: dict[str, list[dict]] = {arm: [] for arm in GROUPS}
        try:
            with httpx.Client(timeout=60) as client:
                for row in rows:
                    for arm in GROUPS:
                        start = time.monotonic()
                        if arm == "rules":
                            prediction = rules_prediction(row)
                        elif arm == "governed":
                            prediction = call_governed(client, governed_url, key, row)
                        else:
                            prediction = call_model(client, base + "/chat/completions", key, model, row, arm == "rag")
                        elapsed = (time.monotonic() - start) * 1000
                        results_by_arm[arm].append(normalized_prediction(row["id"], prediction, elapsed, arm))
            if args.raw_output_dir:
                args.raw_output_dir.mkdir(parents=True, exist_ok=True)
                for arm in GROUPS:
                    target = args.raw_output_dir / f"{arm}.json"
                    target.write_text(json.dumps(results_by_arm[arm], ensure_ascii=False, indent=2) + "\n")
                    result.setdefault("raw_output_sha256", {})[arm] = digest(target.read_bytes())
            result["groups"] = [
                {"id": arm, "status": "EXECUTED_UNREVIEWED", "runs_per_case": 1,
                 "metrics": grade(rows, results_by_arm[arm])}
                for arm in GROUPS
            ]
            result["status"] = "EXECUTED_UNREVIEWED"
        except (ValueError, KeyError, TypeError, httpx.HTTPError, OSError) as exc:
            # Never report partial execution as a passing experiment.
            result["status"] = "FAILED_CLOSED"
            result["reasons"] = ["MODEL_COMPARISON_INCOMPLETE", type(exc).__name__]
            result["groups"] = [
                {"id": arm, "status": "INCOMPLETE", "metrics": {}, "runs_per_case": 1}
                for arm in GROUPS
            ]
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 1 if result["status"] == "FAILED_CLOSED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
