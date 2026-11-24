#!/usr/bin/env python3
"""Create a fail-closed manifest for an immutable GlobalInfra API image.

The signed release-evidence envelope is produced before the image exists, so
the image digest cannot be embedded in that envelope without creating a
circular digest.  This manifest is the bridge: it validates that the evidence
belongs to the source commit and passed every release gate, then binds its
SHA-256 to the registry image digest and CI run that produced the image.

The image itself carries the source commit and evidence SHA-256 as OCI labels;
GitHub's build-provenance attestation signs the resulting image digest.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "services" / "api"
sys.path.insert(0, str(API))

from app.evaluation_artifacts import verify_release_evidence  # noqa: E402


SCHEMA = "globalinfra.release-manifest.v1"
SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
COMMIT_SHA = re.compile(r"[0-9a-f]{40,64}\Z")
GHCR_REPOSITORY = re.compile(
    r"ghcr\.io/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?"
    r"(?:/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?)+\Z"
)
GITHUB_ACTIONS_RUN = re.compile(
    r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/[0-9]+\Z"
)
REQUIRED_VALIDATION_GATES = (
    "web_build",
    "migration_check",
    "full_stack_smoke",
)


class ManifestError(ValueError):
    """Raised when an input cannot represent a promotable release."""


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise ManifestError("release evidence must be a JSON object")
    return value


def _validate_evidence(
    envelope: dict[str, Any], expected_commit: str, public_key: bytes
) -> None:
    payload = envelope.get("payload")
    signature = envelope.get("signature")
    if not isinstance(payload, dict) or not isinstance(signature, dict):
        raise ManifestError("release evidence envelope is incomplete")
    if signature.get("scheme") != "ED25519":
        raise ManifestError("champion release evidence must use ED25519")
    if not signature.get("key_id") or not signature.get("value"):
        raise ManifestError("release evidence signature metadata is incomplete")

    verification = verify_release_evidence(
        envelope,
        expected_commit=expected_commit,
        ed25519_public_key=public_key,
        repo_root=ROOT,
    )
    if verification.get("status") != "VERIFIED":
        reasons = ",".join(verification.get("reasons") or ["UNKNOWN"])
        raise ManifestError(f"release evidence verification failed: {reasons}")

    source = payload.get("source")
    if not isinstance(source, dict) or source.get("commit") != expected_commit:
        raise ManifestError("release evidence commit does not match image source")
    if source.get("dirty") is not False:
        raise ManifestError("release evidence source must be a clean checkout")

    totals = payload.get("totals")
    if not isinstance(totals, dict) or totals.get("evidence_completeness") != "COMPLETE":
        raise ManifestError("release evidence suites are incomplete")
    suites = payload.get("suites")
    if not isinstance(suites, list) or not suites:
        raise ManifestError("release evidence contains no evaluation suites")
    if any(
        not isinstance(suite, dict)
        or suite.get("evidence_status") != "VERIFIED"
        or suite.get("reported_status") != "PASSED"
        for suite in suites
    ):
        raise ManifestError("every evaluation suite must be verified and passed")

    validation = payload.get("validation")
    if not isinstance(validation, dict):
        raise ManifestError("release validation gates are missing")
    api_tests = validation.get("api_tests")
    if (
        not isinstance(api_tests, dict)
        or api_tests.get("status") != "PASSED"
        or not isinstance(api_tests.get("tests"), int)
        or api_tests["tests"] <= 0
        or api_tests.get("passed") != api_tests.get("tests")
        or api_tests.get("failures") != 0
        or api_tests.get("errors") != 0
        or api_tests.get("skipped") != 0
    ):
        raise ManifestError("API test attestation did not pass without skips")
    for gate in REQUIRED_VALIDATION_GATES:
        if validation.get(gate) != "PASSED":
            raise ManifestError(f"release validation gate did not pass: {gate}")


def build_manifest(
    *,
    evidence_path: Path,
    public_key_path: Path,
    commit: str,
    image: str,
    image_digest: str,
    ci_url: str,
    generated_at: str | None = None,
) -> dict[str, Any]:
    commit = commit.strip().lower()
    image_digest = image_digest.strip().lower()
    image = image.strip()
    if not COMMIT_SHA.fullmatch(commit):
        raise ManifestError("commit must be a full hexadecimal Git SHA")
    if not SHA256_DIGEST.fullmatch(image_digest):
        raise ManifestError("image digest must be sha256 followed by 64 hex characters")
    if not GHCR_REPOSITORY.fullmatch(image):
        raise ManifestError(
            "image must be a lowercase, unqualified-by-digest GHCR repository name"
        )
    if not GITHUB_ACTIONS_RUN.fullmatch(ci_url):
        raise ManifestError("ci-url must identify a GitHub Actions run")

    envelope = _load_object(evidence_path)
    try:
        public_key = public_key_path.read_bytes()
    except OSError as exc:
        raise ManifestError(f"cannot read Ed25519 public key: {public_key_path}") from exc
    _validate_evidence(envelope, commit, public_key)
    evidence_sha256 = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    signature = envelope["signature"]

    return {
        "schema": SCHEMA,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "source": {"commit": commit},
        "evidence": {
            "path": "/run/globalinfra-evidence/release-evidence.json",
            "sha256": evidence_sha256,
            "public_key_sha256": hashlib.sha256(public_key).hexdigest(),
            "signature_scheme": signature["scheme"],
            "key_id": signature["key_id"],
        },
        "image": {
            "repository": image,
            "digest": image_digest,
            "reference": f"{image}@{image_digest}",
        },
        "ci": {"url": ci_url},
        "promotion": {
            "policy": "DIGEST_ONLY",
            "mutable_tags_accepted": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--ci-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        manifest = build_manifest(
            evidence_path=args.evidence,
            public_key_path=args.public_key,
            commit=args.commit,
            image=args.image,
            image_digest=args.image_digest,
            ci_url=args.ci_url,
        )
    except ManifestError as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
