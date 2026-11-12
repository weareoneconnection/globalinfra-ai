import copy
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.evaluation_artifacts import (
    SUITE_SPECS,
    build_release_evidence,
    safe_model_configuration,
    sign_release_payload,
    verify_release_evidence,
)


def test_safe_model_configuration_excludes_credentials_and_endpoint_hosts():
    configuration = safe_model_configuration({
        "LLM_MODE": "auto",
        "OPENAI_COMPAT_BASE_URL": "https://user:password@private-gateway.internal/v1",
        "OPENAI_COMPAT_API_KEY": "secret-cloud-key",
        "OPENAI_COMPAT_MODEL": "approved-cloud-model",
        "LOCAL_LLM_BASE_URL": "http://ollama.private.internal:11434/v1",
        "LOCAL_LLM_MODEL": "approved-local-model",
    })

    encoded = json.dumps(configuration)
    assert configuration["secrets_included"] is False
    assert "secret-cloud-key" not in encoded
    assert "password" not in encoded
    assert "private-gateway.internal" not in encoded
    assert "ollama.private.internal" not in encoded


def _fixture_files(root: Path) -> Path:
    raw = root / "raw"
    raw.mkdir(parents=True)
    for index, spec in enumerate(SUITE_SPECS, start=1):
        dataset = root / spec["dataset"]
        dataset.parent.mkdir(parents=True, exist_ok=True)
        dataset.write_text(
            json.dumps({"id": f"case-{index}"}) + "\n", encoding="utf-8"
        )
        (raw / spec["output"]).write_text(
            json.dumps(
                {
                    "suite": spec["id"],
                    "status": "PASSED",
                    "total_cases": 1,
                    "metrics": {"accuracy": 100.0},
                    "gates": {"accuracy": True},
                }
            ),
            encoding="utf-8",
        )
    return raw


def _packaged_fixture_files(root: Path) -> Path:
    """Mirror the API Docker image, which ships /app/evals but not the repo."""

    raw = root / "raw"
    raw.mkdir(parents=True)
    for index, spec in enumerate(SUITE_SPECS, start=1):
        dataset = root / "evals" / Path(spec["dataset"]).name
        dataset.parent.mkdir(parents=True, exist_ok=True)
        dataset.write_text(
            json.dumps({"id": f"case-{index}"}) + "\n", encoding="utf-8"
        )
        (raw / spec["output"]).write_text(
            json.dumps({
                "suite": spec["id"],
                "status": "PASSED",
                "total_cases": 1,
                "metrics": {"accuracy": 100.0},
                "gates": {"accuracy": True},
            }),
            encoding="utf-8",
        )
    return raw


def test_release_evidence_resolves_packaged_api_dataset_layout(tmp_path):
    raw = _packaged_fixture_files(tmp_path)
    envelope = build_release_evidence(
        raw_dir=raw,
        repo_root=tmp_path,
        git_info={"commit": "packaged", "dirty": False, "tracked_changes": []},
        hmac_key="packaged-layout-test-key",
    )

    result = verify_release_evidence(
        envelope,
        expected_commit="packaged",
        hmac_key="packaged-layout-test-key",
        repo_root=tmp_path,
    )

    assert result["status"] == "VERIFIED"
    assert result["reasons"] == []
    assert all(
        suite["dataset"]["path"] == spec["dataset"]
        for suite, spec in zip(envelope["payload"]["suites"], SUITE_SPECS)
    )


def _ed25519_keypair() -> tuple[str, str]:
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return private_pem, public_pem


def test_ed25519_release_evidence_uses_public_only_runtime_verification(tmp_path):
    raw = _fixture_files(tmp_path)
    private_pem, public_pem = _ed25519_keypair()
    envelope = build_release_evidence(
        raw_dir=raw,
        repo_root=tmp_path,
        generated_at="2026-11-10T00:00:00Z",
        git_info={"commit": "ed25519-commit", "dirty": False, "tracked_changes": []},
        # Exercise the literal-\\n representation used by secret stores.
        ed25519_private_key=private_pem.replace("\n", "\\n"),
        key_id="ci:release-v1",
    )

    result = verify_release_evidence(
        envelope,
        expected_commit="ed25519-commit",
        ed25519_public_key=public_pem.replace("\n", "\\n"),
        repo_root=tmp_path,
    )

    assert result == {
        "status": "VERIFIED",
        "reasons": [],
        "scheme": "ED25519",
        "key_id": "ci:release-v1",
        "commit": "ed25519-commit",
    }
    assert "VERIFICATION_KEY_MISSING" in verify_release_evidence(envelope)[
        "reasons"
    ]

    _, wrong_public = _ed25519_keypair()
    wrong_key = verify_release_evidence(
        envelope, ed25519_public_key=wrong_public
    )
    assert "SIGNATURE_MISMATCH" in wrong_key["reasons"]

    tampered = copy.deepcopy(envelope)
    tampered["payload"]["suites"][0]["metrics"]["accuracy"] = 98.0
    assert "SIGNATURE_MISMATCH" in verify_release_evidence(
        tampered, ed25519_public_key=public_pem
    )["reasons"]

    invalid_key = verify_release_evidence(
        envelope, ed25519_public_key="not-a-public-key"
    )
    assert "VERIFICATION_KEY_INVALID" in invalid_key["reasons"]


def test_signed_release_evidence_verifies_commit_and_datasets(tmp_path):
    raw = _fixture_files(tmp_path)
    envelope = build_release_evidence(
        raw_dir=raw,
        repo_root=tmp_path,
        generated_at="2026-11-08T00:00:00Z",
        git_info={"commit": "abc123", "dirty": False, "tracked_changes": []},
        hmac_key="test-signing-key",
        key_id="test:v1",
    )

    result = verify_release_evidence(
        envelope,
        expected_commit="abc123",
        hmac_key="test-signing-key",
        repo_root=tmp_path,
    )

    assert result == {
        "status": "VERIFIED",
        "reasons": [],
        "scheme": "HMAC-SHA256",
        "key_id": "test:v1",
        "commit": "abc123",
    }


def test_tamper_commit_mismatch_and_unsigned_artifacts_fail_closed(tmp_path):
    raw = _fixture_files(tmp_path)
    envelope = build_release_evidence(
        raw_dir=raw,
        repo_root=tmp_path,
        git_info={"commit": "abc123", "dirty": False, "tracked_changes": []},
        hmac_key="test-signing-key",
    )
    tampered = copy.deepcopy(envelope)
    tampered["payload"]["suites"][0]["metrics"]["accuracy"] = 99.0
    assert "SIGNATURE_MISMATCH" in verify_release_evidence(
        tampered, hmac_key="test-signing-key"
    )["reasons"]

    mismatch = verify_release_evidence(
        envelope, expected_commit="different", hmac_key="test-signing-key"
    )
    assert mismatch["status"] == "UNVERIFIED"
    assert "COMMIT_MISMATCH" in mismatch["reasons"]

    unsigned = build_release_evidence(
        raw_dir=raw,
        repo_root=tmp_path,
        git_info={"commit": "abc123", "dirty": False, "tracked_changes": []},
    )
    assert "SIGNATURE_MISSING" in verify_release_evidence(unsigned)["reasons"]


def test_missing_runner_output_makes_bundle_incomplete(tmp_path):
    raw = _fixture_files(tmp_path)
    (raw / SUITE_SPECS[0]["output"]).unlink()
    envelope = build_release_evidence(
        raw_dir=raw,
        repo_root=tmp_path,
        git_info={"commit": "abc123", "dirty": False, "tracked_changes": []},
        hmac_key="test-signing-key",
    )

    result = verify_release_evidence(envelope, hmac_key="test-signing-key")

    assert result["status"] == "UNVERIFIED"
    assert "EVIDENCE_INCOMPLETE" in result["reasons"]
    assert envelope["payload"]["suites"][0]["verification_errors"] == [
        "OUTPUT_MISSING"
    ]


def test_runner_gate_contract_rejects_numeric_or_status_mismatched_gates(tmp_path):
    raw = _fixture_files(tmp_path)
    output = raw / SUITE_SPECS[0]["output"]
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["gates"] = {"accuracy": 100.0}
    output.write_text(json.dumps(payload), encoding="utf-8")

    envelope = build_release_evidence(
        raw_dir=raw,
        repo_root=tmp_path,
        git_info={"commit": "abc123", "dirty": False, "tracked_changes": []},
        hmac_key="test-signing-key",
    )
    suite = envelope["payload"]["suites"][0]
    assert suite["evidence_status"] == "UNVERIFIED"
    assert "GATES_INVALID" in suite["verification_errors"]
    assert verify_release_evidence(
        envelope, hmac_key="test-signing-key", repo_root=tmp_path
    )["status"] == "UNVERIFIED"

    payload["gates"] = {"accuracy": False}
    output.write_text(json.dumps(payload), encoding="utf-8")
    mismatch = build_release_evidence(
        raw_dir=raw,
        repo_root=tmp_path,
        git_info={"commit": "abc123", "dirty": False, "tracked_changes": []},
        hmac_key="test-signing-key",
    )
    assert "STATUS_GATE_MISMATCH" in mismatch["payload"]["suites"][0][
        "verification_errors"
    ]


def test_verifier_binds_suite_ids_to_canonical_dataset_and_runner(tmp_path):
    raw = _fixture_files(tmp_path)
    envelope = build_release_evidence(
        raw_dir=raw,
        repo_root=tmp_path,
        git_info={"commit": "abc123", "dirty": False, "tracked_changes": []},
        hmac_key="test-signing-key",
    )
    payload = copy.deepcopy(envelope["payload"])
    payload["suites"][0]["dataset"]["path"] = SUITE_SPECS[1]["dataset"]
    payload["suites"][0]["runner_output"]["filename"] = SUITE_SPECS[1]["output"]
    resigned = sign_release_payload(payload, hmac_key="test-signing-key")

    result = verify_release_evidence(
        resigned,
        expected_commit="abc123",
        hmac_key="test-signing-key",
        repo_root=tmp_path,
    )

    assert result["status"] == "UNVERIFIED"
    assert "DATASET_PATH_MISMATCH:AI_OUTBOUND_COMPETITION_EVIDENCE" in result[
        "reasons"
    ]
    assert "RUNNER_OUTPUT_MISMATCH:AI_OUTBOUND_COMPETITION_EVIDENCE" in result[
        "reasons"
    ]


def test_verifier_rejects_resigned_invalid_suite_contract(tmp_path):
    raw = _fixture_files(tmp_path)
    envelope = build_release_evidence(
        raw_dir=raw,
        repo_root=tmp_path,
        git_info={"commit": "abc123", "dirty": False, "tracked_changes": []},
        hmac_key="test-signing-key",
    )
    payload = copy.deepcopy(envelope["payload"])
    suite = payload["suites"][0]
    suite["reported_status"] = "CLAIMED"
    suite["metrics"] = {"accuracy": float("nan")}
    suite["verification_errors"] = None
    suite["runner_output"]["sha256"] = "not-a-digest"
    resigned = sign_release_payload(payload, hmac_key="test-signing-key")

    result = verify_release_evidence(
        resigned,
        expected_commit="abc123",
        hmac_key="test-signing-key",
        repo_root=tmp_path,
    )

    assert result["status"] == "UNVERIFIED"
    assert "SUITE_STATUS_INVALID:AI_OUTBOUND_COMPETITION_EVIDENCE" in result["reasons"]
    assert "SUITE_METRICS_INVALID:AI_OUTBOUND_COMPETITION_EVIDENCE" in result["reasons"]
    assert "SUITE_EVIDENCE_UNVERIFIED:AI_OUTBOUND_COMPETITION_EVIDENCE" in result["reasons"]
    assert "RUNNER_OUTPUT_DIGEST_INVALID:AI_OUTBOUND_COMPETITION_EVIDENCE" in result["reasons"]
