"""Build and verify release evidence from real evaluation outputs.

This module deliberately separates two questions:

* what the evaluation runners reported; and
* whether the release-evidence envelope is authentic and belongs to the
  expected source commit.

No suite result is synthesized here.  Missing or malformed runner output is
recorded as ``UNVERIFIED``.  Production releases use an Ed25519 private key in
CI and expose only the corresponding public key to the running API. HMAC-SHA256
is retained for local/backwards-compatible envelopes; KMS signers remain
pluggable through the byte-oriented callable contract.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import base64
import binascii
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


EVIDENCE_SCHEMA = "globalinfra.release-evidence.v1"
SIGNATURE_SCHEMA = "globalinfra.release-evidence-signature.v1"

SUITE_SPECS: tuple[dict[str, str], ...] = (
    {
        "id": "AI_OUTBOUND_COMPETITION_EVIDENCE",
        "slug": "ai_outbound",
        "output": "ai_outbound.json",
        "dataset": "services/api/evals/competition_outbound.jsonl",
    },
    {
        "id": "AGENT_ORGANIZATION",
        "slug": "agent_organization",
        "output": "agent_organization.json",
        "dataset": "services/api/evals/agent_org.jsonl",
    },
    {
        "id": "ASSISTANT_DISPATCH",
        "slug": "assistant_dispatch",
        "output": "assistant_dispatch.json",
        "dataset": "services/api/evals/assistant_dispatch.jsonl",
    },
)

KmsSigner = Callable[[bytes], Mapping[str, str]]
KmsVerifier = Callable[[bytes, Mapping[str, Any]], bool]


def _pem_bytes(value: str | bytes) -> bytes:
    """Accept normal PEM or the literal ``\\n`` form used by secret stores."""

    if isinstance(value, bytes):
        return value.replace(b"\\n", b"\n").strip() + b"\n"
    return value.replace("\\n", "\n").strip().encode("utf-8") + b"\n"


def _load_ed25519_private_key(value: str | bytes) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(_pem_bytes(value), password=None)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Ed25519 signing key must be an unencrypted PKCS8 PEM private key"
        ) from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Signing key is not an Ed25519 private key")
    return key


def _load_ed25519_public_key(value: str | bytes) -> Ed25519PublicKey:
    try:
        key = serialization.load_pem_public_key(_pem_bytes(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("Ed25519 verification key must be a PEM public key") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Verification key is not an Ed25519 public key")
    return key


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonl_record_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as stream:
        return sum(1 for line in stream if line.strip())


def _dataset_path(repo_root: Path, canonical_path: str) -> Path:
    """Resolve a suite dataset in a checkout or the packaged API image.

    Release metadata always keeps the repository-relative canonical path. The
    API Docker image intentionally contains only ``services/api`` and places
    its runtime datasets at ``/app/evals``; this exact filename fallback lets
    the runtime verify the same bytes without pretending the full repository
    was copied into the image.
    """

    checkout_path = repo_root / canonical_path
    if checkout_path.is_file():
        return checkout_path
    packaged_path = repo_root / "evals" / Path(canonical_path).name
    return packaged_path if packaged_path.is_file() else checkout_path


def _git_output(repo_root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def git_state(repo_root: Path) -> dict[str, Any]:
    """Return the source commit and tracked-worktree state.

    Generated evidence is normally written outside the checkout in CI.  Only
    tracked changes count as a dirty code state so that an untracked artifact
    does not invalidate the commit it describes.
    """

    commit = _git_output(repo_root, "rev-parse", "HEAD")
    tracked_status = _git_output(
        repo_root, "status", "--porcelain", "--untracked-files=no"
    )
    return {
        "commit": commit,
        "dirty": None if tracked_status is None else bool(tracked_status),
        "tracked_changes": [] if not tracked_status else tracked_status.splitlines(),
    }


def safe_model_configuration(
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Describe model routing without exposing credentials or full URLs."""

    env = os.environ if environment is None else environment
    mode = env.get("LLM_MODE", "mock").strip().lower() or "mock"
    cloud_url = env.get("OPENAI_COMPAT_BASE_URL", "").strip()
    local_url = env.get("LOCAL_LLM_BASE_URL", "").strip()

    return {
        "mode": mode,
        "providers": [
            {
                "id": "openai_compatible",
                "model": env.get("OPENAI_COMPAT_MODEL") or None,
                "configured": bool(
                    cloud_url
                    and env.get("OPENAI_COMPAT_MODEL")
                    and env.get("OPENAI_COMPAT_API_KEY")
                ),
            },
            {
                "id": "local_openai_compatible",
                "model": env.get("LOCAL_LLM_MODEL") or None,
                "configured": bool(local_url and env.get("LOCAL_LLM_MODEL")),
            },
        ],
        "secrets_included": False,
    }


def _read_suite(
    spec: Mapping[str, str], raw_dir: Path, repo_root: Path
) -> dict[str, Any]:
    output_path = raw_dir / spec["output"]
    dataset_path = _dataset_path(repo_root, spec["dataset"])
    errors: list[str] = []
    payload: dict[str, Any] = {}

    if not output_path.is_file():
        errors.append("OUTPUT_MISSING")
    else:
        try:
            loaded = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
            else:
                errors.append("OUTPUT_NOT_AN_OBJECT")
        except (OSError, json.JSONDecodeError):
            errors.append("OUTPUT_INVALID_JSON")

    if not dataset_path.is_file():
        errors.append("DATASET_MISSING")

    reported_suite = payload.get("suite")
    if payload and reported_suite != spec["id"]:
        errors.append("SUITE_ID_MISMATCH")

    case_count = payload.get("total_cases")
    if payload and (type(case_count) is not int or case_count <= 0):
        errors.append("TOTAL_CASES_INVALID")
        case_count = None

    metrics = payload.get("metrics")
    gates = payload.get("gates")
    if payload and not isinstance(metrics, dict):
        errors.append("METRICS_MISSING")
        metrics = {}
    elif payload and (
        not metrics
        or any(
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for key, value in metrics.items()
        )
    ):
        errors.append("METRICS_INVALID")
    if payload and not isinstance(gates, dict):
        errors.append("GATES_MISSING")
        gates = {}
    elif payload and (
        not gates
        or any(not isinstance(key, str) or type(value) is not bool for key, value in gates.items())
    ):
        errors.append("GATES_INVALID")

    dataset_count = None
    dataset_sha256 = None
    if dataset_path.is_file():
        dataset_count = _jsonl_record_count(dataset_path)
        dataset_sha256 = sha256_file(dataset_path)
        if case_count is not None and dataset_count != case_count:
            errors.append("CASE_COUNT_DATASET_MISMATCH")

    reported_status = payload.get("status") if payload else None
    if payload and reported_status not in {"PASSED", "FAILED"}:
        errors.append("STATUS_INVALID")
        reported_status = None
    elif payload and isinstance(gates, dict) and gates and all(
        type(value) is bool for value in gates.values()
    ):
        if (reported_status == "PASSED") != all(gates.values()):
            errors.append("STATUS_GATE_MISMATCH")

    return {
        "id": spec["id"],
        "slug": spec["slug"],
        "evidence_status": "VERIFIED" if not errors else "UNVERIFIED",
        "verification_errors": errors,
        "reported_status": reported_status,
        "case_count": case_count,
        "metrics": metrics or {},
        "gates": gates or {},
        "dataset": {
            "path": spec["dataset"],
            "records": dataset_count,
            "sha256": dataset_sha256,
        },
        "runner_output": {
            "filename": spec["output"],
            "sha256": sha256_file(output_path) if output_path.is_file() else None,
        },
    }


def build_release_payload(
    *,
    raw_dir: Path,
    repo_root: Path,
    ci_url: str | None = None,
    generated_at: str | None = None,
    environment: Mapping[str, str] | None = None,
    git_info: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an unsigned payload from the three expected runner outputs."""

    suites = [_read_suite(spec, raw_dir, repo_root) for spec in SUITE_SPECS]
    statuses = Counter(
        suite["reported_status"] or "UNREPORTED" for suite in suites
    )
    case_counts = [suite["case_count"] for suite in suites]
    all_complete = all(suite["evidence_status"] == "VERIFIED" for suite in suites)

    return {
        "schema": EVIDENCE_SCHEMA,
        "generated_at": generated_at or _utc_now(),
        "source": dict(git_info) if git_info is not None else git_state(repo_root),
        "ci": {"url": ci_url},
        "model_configuration": safe_model_configuration(environment),
        "totals": {
            "expected_suite_count": len(SUITE_SPECS),
            "complete_suite_count": sum(
                suite["evidence_status"] == "VERIFIED" for suite in suites
            ),
            "case_count": sum(count for count in case_counts if isinstance(count, int)),
            "reported_status_counts": dict(sorted(statuses.items())),
            "evidence_completeness": "COMPLETE" if all_complete else "INCOMPLETE",
        },
        "suites": suites,
    }


def sign_release_payload(
    payload: Mapping[str, Any],
    *,
    ed25519_private_key: str | bytes | None = None,
    hmac_key: str | bytes | None = None,
    key_id: str | None = None,
    kms_signer: KmsSigner | None = None,
) -> dict[str, Any]:
    """Wrap a payload in Ed25519, HMAC, KMS, or an unsigned envelope.

    KMS and Ed25519 take precedence over the legacy HMAC path so a deployment
    cannot accidentally downgrade when both old and new secrets are present.
    """

    message = _canonical_json(payload)
    if kms_signer is not None:
        supplied = dict(kms_signer(message))
        signature = {
            "schema": SIGNATURE_SCHEMA,
            "scheme": supplied.get("scheme", "KMS"),
            "key_id": supplied.get("key_id") or key_id,
            "value": supplied.get("value"),
        }
    elif ed25519_private_key:
        private_key = _load_ed25519_private_key(ed25519_private_key)
        signature = {
            "schema": SIGNATURE_SCHEMA,
            "scheme": "ED25519",
            "key_id": key_id or "ci:ed25519",
            "value": base64.b64encode(private_key.sign(message)).decode("ascii"),
        }
    elif hmac_key:
        key_bytes = hmac_key.encode("utf-8") if isinstance(hmac_key, str) else hmac_key
        signature = {
            "schema": SIGNATURE_SCHEMA,
            "scheme": "HMAC-SHA256",
            "key_id": key_id or "environment",
            "value": hmac.new(key_bytes, message, hashlib.sha256).hexdigest(),
        }
    else:
        signature = {
            "schema": SIGNATURE_SCHEMA,
            "scheme": "UNSIGNED",
            "key_id": key_id,
            "value": None,
        }
    return {"payload": dict(payload), "signature": signature}


def build_release_evidence(
    *,
    raw_dir: Path,
    repo_root: Path,
    ci_url: str | None = None,
    generated_at: str | None = None,
    environment: Mapping[str, str] | None = None,
    git_info: Mapping[str, Any] | None = None,
    ed25519_private_key: str | bytes | None = None,
    hmac_key: str | bytes | None = None,
    key_id: str | None = None,
    kms_signer: KmsSigner | None = None,
) -> dict[str, Any]:
    payload = build_release_payload(
        raw_dir=raw_dir,
        repo_root=repo_root,
        ci_url=ci_url,
        generated_at=generated_at,
        environment=environment,
        git_info=git_info,
    )
    return sign_release_payload(
        payload,
        ed25519_private_key=ed25519_private_key,
        hmac_key=hmac_key,
        key_id=key_id,
        kms_signer=kms_signer,
    )


def verify_release_evidence(
    envelope: Mapping[str, Any],
    *,
    expected_commit: str | None = None,
    ed25519_public_key: str | bytes | None = None,
    hmac_key: str | bytes | None = None,
    kms_verifier: KmsVerifier | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Verify signature, source commit and optional on-disk dataset digests."""

    reasons: list[str] = []
    payload = envelope.get("payload")
    signature = envelope.get("signature")
    if not isinstance(payload, Mapping) or not isinstance(signature, Mapping):
        return {"status": "UNVERIFIED", "reasons": ["ENVELOPE_INVALID"]}

    message = _canonical_json(payload)
    scheme = signature.get("scheme")
    if signature.get("schema") != SIGNATURE_SCHEMA:
        reasons.append("SIGNATURE_SCHEMA_MISMATCH")
    if payload.get("schema") != EVIDENCE_SCHEMA:
        reasons.append("EVIDENCE_SCHEMA_MISMATCH")
    if scheme == "ED25519":
        if not ed25519_public_key:
            reasons.append("VERIFICATION_KEY_MISSING")
        else:
            try:
                public_key = _load_ed25519_public_key(ed25519_public_key)
            except ValueError:
                reasons.append("VERIFICATION_KEY_INVALID")
            else:
                supplied = signature.get("value")
                try:
                    decoded = base64.b64decode(supplied, validate=True)
                except (binascii.Error, TypeError, ValueError):
                    reasons.append("SIGNATURE_MALFORMED")
                else:
                    try:
                        public_key.verify(decoded, message)
                    except InvalidSignature:
                        reasons.append("SIGNATURE_MISMATCH")
    elif scheme == "HMAC-SHA256":
        if not hmac_key:
            reasons.append("VERIFICATION_KEY_MISSING")
        else:
            key_bytes = hmac_key.encode("utf-8") if isinstance(hmac_key, str) else hmac_key
            expected = hmac.new(key_bytes, message, hashlib.sha256).hexdigest()
            supplied = signature.get("value")
            if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
                reasons.append("SIGNATURE_MISMATCH")
    elif scheme == "UNSIGNED" or not scheme:
        reasons.append("SIGNATURE_MISSING")
    elif kms_verifier is None:
        reasons.append("KMS_VERIFIER_MISSING")
    elif not kms_verifier(message, signature):
        reasons.append("SIGNATURE_MISMATCH")

    source = payload.get("source")
    if not isinstance(source, Mapping):
        reasons.append("SOURCE_METADATA_MISSING")
    else:
        commit = source.get("commit")
        if not isinstance(commit, str) or not commit.strip():
            reasons.append("SOURCE_COMMIT_MISSING")
        if expected_commit and commit != expected_commit:
            reasons.append("COMMIT_MISMATCH")
        if source.get("dirty") is True:
            reasons.append("DIRTY_WORKTREE")
        elif source.get("dirty") is not False:
            reasons.append("SOURCE_DIRTY_STATE_UNKNOWN")

    totals = payload.get("totals")
    if not isinstance(totals, Mapping) or totals.get("evidence_completeness") != "COMPLETE":
        reasons.append("EVIDENCE_INCOMPLETE")

    suites = payload.get("suites")
    canonical_specs = {spec["id"]: spec for spec in SUITE_SPECS}
    seen_suite_ids: list[str] = []
    suite_case_total = 0
    verified_suite_count = 0
    if not isinstance(suites, list):
        reasons.append("SUITES_MISSING")
    else:
        for suite in suites:
            if not isinstance(suite, Mapping):
                reasons.append("SUITE_METADATA_INVALID")
                continue
            suite_id = suite.get("id")
            if not isinstance(suite_id, str) or suite_id not in canonical_specs:
                reasons.append(f"SUITE_ID_UNKNOWN:{suite_id or 'missing'}")
                continue
            if suite_id in seen_suite_ids:
                reasons.append(f"SUITE_ID_DUPLICATE:{suite_id}")
            seen_suite_ids.append(suite_id)
            spec = canonical_specs[suite_id]
            if suite.get("slug") != spec["slug"]:
                reasons.append(f"SUITE_SLUG_MISMATCH:{suite_id}")
            if suite.get("evidence_status") != "VERIFIED" or suite.get(
                "verification_errors"
            ) != []:
                reasons.append(f"SUITE_EVIDENCE_UNVERIFIED:{suite_id}")
            else:
                verified_suite_count += 1

            reported_status = suite.get("reported_status")
            if reported_status not in {"PASSED", "FAILED"}:
                reasons.append(f"SUITE_STATUS_INVALID:{suite_id}")

            metrics = suite.get("metrics")
            if not isinstance(metrics, Mapping) or not metrics or any(
                not isinstance(key, str)
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for key, value in metrics.items()
            ):
                reasons.append(f"SUITE_METRICS_INVALID:{suite_id}")

            gates = suite.get("gates")
            if not isinstance(gates, Mapping) or not gates or any(
                not isinstance(key, str) or type(value) is not bool
                for key, value in gates.items()
            ):
                reasons.append(f"SUITE_GATES_INVALID:{suite_id}")
            elif reported_status in {"PASSED", "FAILED"} and (
                (reported_status == "PASSED") != all(gates.values())
            ):
                reasons.append(f"SUITE_STATUS_GATE_MISMATCH:{suite_id}")

            case_count = suite.get("case_count")
            if type(case_count) is not int or case_count <= 0:
                reasons.append(f"SUITE_CASE_COUNT_INVALID:{suite_id}")
            else:
                suite_case_total += case_count

            dataset = suite.get("dataset")
            if not isinstance(dataset, Mapping):
                reasons.append(f"DATASET_METADATA_MISSING:{suite_id}")
                continue
            if dataset.get("path") != spec["dataset"]:
                reasons.append(f"DATASET_PATH_MISMATCH:{suite_id}")
            dataset_records = dataset.get("records")
            if type(dataset_records) is not int or dataset_records <= 0:
                reasons.append(f"DATASET_RECORD_COUNT_INVALID:{suite_id}")
            runner_output = suite.get("runner_output")
            if not isinstance(runner_output, Mapping) or runner_output.get(
                "filename"
            ) != spec["output"]:
                reasons.append(f"RUNNER_OUTPUT_MISMATCH:{suite_id}")
            elif not isinstance(runner_output.get("sha256"), str) or not all(
                character in "0123456789abcdef"
                for character in runner_output["sha256"].lower()
            ) or len(runner_output["sha256"]) != 64:
                reasons.append(f"RUNNER_OUTPUT_DIGEST_INVALID:{suite_id}")
            if repo_root is not None:
                path = _dataset_path(repo_root, spec["dataset"])
                expected_digest = dataset.get("sha256")
                if not path.is_file() or sha256_file(path) != expected_digest:
                    reasons.append(f"DATASET_DIGEST_MISMATCH:{suite_id}")
                elif dataset_records != _jsonl_record_count(path):
                    reasons.append(f"DATASET_RECORD_COUNT_MISMATCH:{suite_id}")
                if type(case_count) is int and dataset_records != case_count:
                    reasons.append(f"CASE_COUNT_DATASET_MISMATCH:{suite_id}")

        if set(seen_suite_ids) != set(canonical_specs) or len(seen_suite_ids) != len(
            canonical_specs
        ):
            reasons.append("SUITE_SET_MISMATCH")

    if isinstance(totals, Mapping) and (
        totals.get("expected_suite_count") != len(SUITE_SPECS)
        or totals.get("complete_suite_count") != verified_suite_count
        or totals.get("case_count") != suite_case_total
    ):
        reasons.append("TOTALS_MISMATCH")

    return {
        "status": "VERIFIED" if not reasons else "UNVERIFIED",
        "reasons": sorted(set(reasons)),
        "scheme": scheme,
        "key_id": signature.get("key_id"),
        "commit": source.get("commit") if isinstance(source, Mapping) else None,
    }


def write_release_evidence(path: Path, envelope: Mapping[str, Any]) -> str:
    """Write an envelope atomically and return its file SHA-256."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return sha256_file(path)


def load_release_evidence(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("release evidence must be a JSON object")
    return loaded


def verified_release_summary(
    path: Path,
    *,
    expected_commit: str | None = None,
    ed25519_public_key: str | bytes | None = None,
    hmac_key: str | bytes | None = None,
    kms_verifier: KmsVerifier | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Small API-facing view for later integration into ``competition.py``."""

    raw = path.read_bytes()
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("release evidence must be a JSON object")
    envelope = loaded
    verification = verify_release_evidence(
        envelope,
        expected_commit=expected_commit,
        ed25519_public_key=ed25519_public_key,
        hmac_key=hmac_key,
        kms_verifier=kms_verifier,
        repo_root=repo_root,
    )
    payload = envelope.get("payload", {})
    return {
        "verification": verification,
        "generated_at": payload.get("generated_at"),
        "source": payload.get("source"),
        "ci": payload.get("ci"),
        "model_configuration": payload.get("model_configuration"),
        "totals": payload.get("totals"),
        "suites": payload.get("suites"),
        "validation": payload.get("validation"),
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
    }
