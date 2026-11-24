import hashlib
import json
from pathlib import Path
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.evaluation_artifacts import (
    SUITE_SPECS,
    build_release_payload,
    sign_release_payload,
    write_release_evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_release_manifest import ManifestError, build_manifest


COMMIT = "a" * 40
IMAGE_DIGEST = "sha256:" + "b" * 64


def _signed_evidence(
    tmp_path: Path,
    *,
    commit: str = COMMIT,
    validation_overrides: dict | None = None,
) -> tuple[Path, Path]:
    raw = tmp_path / "raw"
    raw.mkdir()
    for spec in SUITE_SPECS:
        dataset = REPO_ROOT / spec["dataset"]
        case_count = len(
            [line for line in dataset.read_text(encoding="utf-8").splitlines() if line]
        )
        (raw / spec["output"]).write_text(
            json.dumps(
                {
                    "suite": spec["id"],
                    "status": "PASSED",
                    "total_cases": case_count,
                    "metrics": {"accuracy": 100.0},
                    "gates": {"accuracy": True},
                }
            ),
            encoding="utf-8",
        )

    payload = build_release_payload(
        raw_dir=raw,
        repo_root=REPO_ROOT,
        generated_at="2026-11-24T00:00:00Z",
        git_info={"commit": commit, "dirty": False, "tracked_changes": []},
    )
    payload["validation"] = {
        "api_tests": {
            "status": "PASSED",
            "tests": 3,
            "passed": 3,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
        },
        "web_build": "PASSED",
        "migration_check": "PASSED",
        "full_stack_smoke": "PASSED",
    }
    payload["validation"].update(validation_overrides or {})
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    envelope = sign_release_payload(
        payload,
        ed25519_private_key=private_pem,
        key_id="github-actions:release-v1",
    )
    evidence = tmp_path / "release-evidence.json"
    write_release_evidence(evidence, envelope)
    public_key = tmp_path / "release-evidence-public.pem"
    public_key.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return evidence, public_key


def test_release_manifest_binds_verified_evidence_to_image_digest(tmp_path):
    evidence, public_key = _signed_evidence(tmp_path)

    manifest = build_manifest(
        evidence_path=evidence,
        public_key_path=public_key,
        commit=COMMIT,
        image="ghcr.io/weareoneconnection/globalinfra-api",
        image_digest=IMAGE_DIGEST,
        ci_url="https://github.com/weareoneconnection/globalinfra-ai/actions/runs/1",
        generated_at="2026-11-24T00:01:00Z",
    )

    assert manifest["source"]["commit"] == COMMIT
    assert manifest["image"]["reference"].endswith(f"@{IMAGE_DIGEST}")
    assert manifest["evidence"]["signature_scheme"] == "ED25519"
    assert manifest["evidence"]["sha256"] == hashlib.sha256(
        evidence.read_bytes()
    ).hexdigest()
    assert manifest["evidence"]["public_key_sha256"] == hashlib.sha256(
        public_key.read_bytes()
    ).hexdigest()
    assert manifest["promotion"] == {
        "policy": "DIGEST_ONLY",
        "mutable_tags_accepted": False,
    }


def test_release_manifest_rejects_tampered_evidence(tmp_path):
    evidence, public_key = _signed_evidence(tmp_path)
    envelope = json.loads(evidence.read_text(encoding="utf-8"))
    envelope["payload"]["suites"][0]["metrics"]["accuracy"] = 99.0
    evidence.write_text(json.dumps(envelope), encoding="utf-8")

    try:
        build_manifest(
            evidence_path=evidence,
            public_key_path=public_key,
            commit=COMMIT,
            image="ghcr.io/weareoneconnection/globalinfra-api",
            image_digest=IMAGE_DIGEST,
            ci_url="https://github.com/weareoneconnection/globalinfra-ai/actions/runs/1",
        )
    except ManifestError as exc:
        assert "SIGNATURE_MISMATCH" in str(exc)
    else:
        raise AssertionError("tampered evidence must not produce a manifest")


def test_release_manifest_rejects_evidence_for_another_commit(tmp_path):
    evidence, public_key = _signed_evidence(tmp_path, commit="c" * 40)

    try:
        build_manifest(
            evidence_path=evidence,
            public_key_path=public_key,
            commit=COMMIT,
            image="ghcr.io/weareoneconnection/globalinfra-api",
            image_digest=IMAGE_DIGEST,
            ci_url="https://github.com/weareoneconnection/globalinfra-ai/actions/runs/1",
        )
    except ManifestError as exc:
        assert "COMMIT_MISMATCH" in str(exc)
    else:
        raise AssertionError("evidence for another commit must not produce a manifest")


def test_release_manifest_rejects_failed_release_gate(tmp_path):
    evidence, public_key = _signed_evidence(
        tmp_path, validation_overrides={"web_build": "FAILED"}
    )

    try:
        build_manifest(
            evidence_path=evidence,
            public_key_path=public_key,
            commit=COMMIT,
            image="ghcr.io/weareoneconnection/globalinfra-api",
            image_digest=IMAGE_DIGEST,
            ci_url="https://github.com/weareoneconnection/globalinfra-ai/actions/runs/1",
        )
    except ManifestError as exc:
        assert "web_build" in str(exc)
    else:
        raise AssertionError("failed release gates must not produce a manifest")


def test_release_manifest_rejects_untrusted_public_key(tmp_path):
    evidence, public_key = _signed_evidence(tmp_path)
    other_key = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key.write_bytes(other_key)

    try:
        build_manifest(
            evidence_path=evidence,
            public_key_path=public_key,
            commit=COMMIT,
            image="ghcr.io/weareoneconnection/globalinfra-api",
            image_digest=IMAGE_DIGEST,
            ci_url="https://github.com/weareoneconnection/globalinfra-ai/actions/runs/1",
        )
    except ManifestError as exc:
        assert "SIGNATURE_MISMATCH" in str(exc)
    else:
        raise AssertionError("an untrusted public key must not produce a manifest")
