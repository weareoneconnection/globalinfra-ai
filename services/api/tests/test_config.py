"""Configuration tests for production security guardrails."""
import hashlib
import hmac
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from app.config import Settings, settings
from app.compose_guard import validate_compose_database
from app.governed_execution import _audit_signature, _audit_signature_is_valid


PRODUCTION_ENV_KEYS = (
    "ENV",
    "APP_ENV",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_ENVIRONMENT",
)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://globalinfra:globalinfra@postgres:5432/globalinfra",
        "postgresql://local:local@localhost:5432/local",
        "sqlite:////tmp/globalinfra-compose.db",
    ],
)
def test_compose_database_guard_allows_only_local_targets_by_default(database_url):
    validate_compose_database(database_url)


def test_compose_database_guard_rejects_external_target_without_explicit_opt_in():
    external = "postgresql+psycopg://user:secret@database.example.test/app"
    with pytest.raises(RuntimeError, match="Refusing to run local Compose"):
        validate_compose_database(external)
    validate_compose_database(external, allow_external=True)


def _public_key_pem() -> str:
    return Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def _clear_production_markers(monkeypatch):
    for key in PRODUCTION_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _set_required_production_controls(monkeypatch):
    monkeypatch.setenv("SOD_ENFORCED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://db/app")
    monkeypatch.setenv("DATA_RESIDENCY_REGION", "ap-southeast-1")
    monkeypatch.setenv(
        "OBJECT_STORAGE_ENDPOINT", "https://s3.ap-southeast-1.amazonaws.com"
    )
    monkeypatch.setenv("QUEUE_URL", "redis://queue.internal:6379/1")
    monkeypatch.setenv("API_KEY", "a" * 32)
    monkeypatch.setenv("OIDC_ISSUER", "https://identity.globalinfra.ai/tenant")
    monkeypatch.setenv("OIDC_AUDIENCE", "globalinfra-api")
    monkeypatch.setenv(
        "OIDC_JWKS_URL",
        "https://identity.globalinfra.ai/tenant/.well-known/jwks.json",
    )
    monkeypatch.setenv("DEFAULT_ORGANIZATION_ID", "competition-tenant")
    monkeypatch.setenv("COMPETITION_SIGNING_SECRET", "c" * 32)
    monkeypatch.setenv("AUDIT_SIGNING_KEY", "d" * 32)
    monkeypatch.setenv("AUDIT_SIGNING_KEY_ID", "audit-2026-11")
    monkeypatch.setenv("EVIDENCE_BUNDLE_REQUIRED", "true")
    monkeypatch.setenv("EVIDENCE_VERIFICATION_PUBLIC_KEY", _public_key_pem())
    monkeypatch.setenv("EVIDENCE_ALLOW_LEGACY_HMAC", "false")
    monkeypatch.delenv("EVIDENCE_SIGNING_KEY", raising=False)
    monkeypatch.delenv("EVIDENCE_SIGNING_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("RELEASE_EVIDENCE_PATH", str(Path(__file__)))
    monkeypatch.setenv("GIT_COMMIT_SHA", "a" * 40)


def _set_fast_launch_controls(monkeypatch):
    _clear_production_markers(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("COMPETITION_FAST_LAUNCH", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://db/app")
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("REQUIRE_API_KEY", "false")
    monkeypatch.setenv("COMPETITION_V6_ENABLED", "true")
    monkeypatch.setenv("SANDBOX_MODE", "true")
    monkeypatch.setenv("SOD_ENFORCED", "true")
    monkeypatch.setenv("AUDIT_MUTATIONS", "true")
    monkeypatch.setenv("EVIDENCE_BUNDLE_REQUIRED", "false")
    monkeypatch.delenv("EVIDENCE_SIGNING_PRIVATE_KEY", raising=False)


def test_production_rejects_missing_security_configuration(monkeypatch):
    _clear_production_markers(monkeypatch)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.delenv("REQUIRE_API_KEY", raising=False)

    with pytest.raises(ValidationError, match="AUTH_MODE"):
        Settings()


def test_production_rejects_missing_api_key_requirement(monkeypatch):
    _clear_production_markers(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.delenv("REQUIRE_API_KEY", raising=False)

    with pytest.raises(ValidationError, match="REQUIRE_API_KEY"):
        Settings()


def test_railway_production_rejects_missing_security_configuration(monkeypatch):
    _clear_production_markers(monkeypatch)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.delenv("REQUIRE_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings()


def test_production_accepts_explicit_security_configuration(monkeypatch):
    _clear_production_markers(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    _set_required_production_controls(monkeypatch)

    configured = Settings()

    assert configured.auth_mode == "oidc"
    assert configured.require_api_key is True
    assert configured.sod_enforced is True


def test_production_accepts_explicit_competition_fast_launch_profile(monkeypatch):
    _set_fast_launch_controls(monkeypatch)

    configured = Settings()

    assert configured.competition_fast_launch is True
    assert configured.deployment_profile == "competition_fast_launch"
    assert configured.auth_mode == "disabled"
    assert configured.sod_enforced is True
    assert configured.evidence_bundle_required is False


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("DATABASE_URL", "sqlite:///./demo.db", "managed production database"),
        ("EVIDENCE_BUNDLE_REQUIRED", "true", "visibly UNVERIFIED"),
        ("SANDBOX_MODE", "false", "SANDBOX_MODE"),
        ("SOD_ENFORCED", "false", "SOD_ENFORCED"),
        ("AUDIT_MUTATIONS", "false", "AUDIT_MUTATIONS"),
    ],
)
def test_fast_launch_keeps_non_negotiable_safety_boundaries(
    monkeypatch, name, value, message
):
    _set_fast_launch_controls(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=message):
        Settings()


def test_production_rejects_demo_storage_and_unsigned_sandbox(monkeypatch):
    _clear_production_markers(monkeypatch)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./demo.db")
    monkeypatch.delenv("COMPETITION_SIGNING_SECRET", raising=False)

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings()


def test_production_rejects_missing_release_evidence_public_key(monkeypatch):
    _clear_production_markers(monkeypatch)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    _set_required_production_controls(monkeypatch)
    monkeypatch.delenv("EVIDENCE_VERIFICATION_PUBLIC_KEY", raising=False)

    with pytest.raises(ValidationError, match="EVIDENCE_VERIFICATION_PUBLIC_KEY"):
        Settings()


def test_production_rejects_release_private_key_in_runtime(monkeypatch):
    _clear_production_markers(monkeypatch)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    _set_required_production_controls(monkeypatch)
    monkeypatch.setenv("EVIDENCE_SIGNING_PRIVATE_KEY", "private-material")

    with pytest.raises(ValidationError, match="must remain in CI/KMS"):
        Settings()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    (
        ("API_KEY", "REPLACE_WITH_API_SERVICE_KEY", "API_KEY"),
        (
            "COMPETITION_SIGNING_SECRET",
            "REPLACE_WITH_32_BYTE_RANDOM_SECRET",
            "COMPETITION_SIGNING_SECRET",
        ),
        ("AUDIT_SIGNING_KEY", "REPLACE_WITH_32_BYTE_AUDIT_RECEIPT_KEY", "AUDIT_SIGNING_KEY"),
        ("DEFAULT_ORGANIZATION_ID", "REPLACE_ORGANIZATION_ID", "DEFAULT_ORGANIZATION_ID"),
        ("DATA_RESIDENCY_REGION", "REPLACE_APPROVED_REGION", "DATA_RESIDENCY_REGION"),
        (
            "OBJECT_STORAGE_ENDPOINT",
            "https://REPLACE_OBJECT_STORAGE_ENDPOINT",
            "OBJECT_STORAGE_ENDPOINT",
        ),
        ("QUEUE_URL", "redis://REPLACE_QUEUE:6379/1", "QUEUE_URL"),
        (
            "DATABASE_URL",
            "postgresql+psycopg://DB_USER:DB_PASSWORD@DB_HOST:5432/DB_NAME",
            "DATABASE_URL",
        ),
        ("GIT_COMMIT_SHA", "REPLACE_WITH_DEPLOYED_COMMIT_SHA", "GIT_COMMIT_SHA"),
        (
            "EVIDENCE_VERIFICATION_PUBLIC_KEY",
            "-----BEGIN PUBLIC KEY-----\\nREPLACE_WITH_ED25519_PUBLIC_KEY_BASE64\\n-----END PUBLIC KEY-----",
            "EVIDENCE_VERIFICATION_PUBLIC_KEY",
        ),
    ),
)
def test_production_rejects_placeholder_controls(
    monkeypatch, name, value, message
):
    _clear_production_markers(monkeypatch)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    _set_required_production_controls(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=message):
        Settings()


def test_production_legacy_hmac_requires_explicit_opt_in_and_separation(monkeypatch):
    _clear_production_markers(monkeypatch)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    _set_required_production_controls(monkeypatch)
    monkeypatch.delenv("EVIDENCE_VERIFICATION_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("EVIDENCE_ALLOW_LEGACY_HMAC", "true")
    monkeypatch.setenv("EVIDENCE_SIGNING_KEY", "e" * 32)

    assert Settings().release_evidence_verifier_configured is True

    monkeypatch.setenv("EVIDENCE_SIGNING_KEY", "c" * 32)
    with pytest.raises(ValidationError, match="must be separated"):
        Settings()


def test_production_rejects_local_audit_outbox(monkeypatch):
    _clear_production_markers(monkeypatch)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("REQUIRE_API_KEY", "true")
    _set_required_production_controls(monkeypatch)
    monkeypatch.setenv("QUEUE_URL", "redis://127.0.0.1:6379/1")

    with pytest.raises(ValidationError, match="QUEUE_URL"):
        Settings()


def test_governance_receipts_prefer_dedicated_audit_key(monkeypatch):
    audit_key = "audit-domain-key-32-characters-long"
    monkeypatch.setattr(settings, "audit_signing_key", audit_key)
    monkeypatch.setattr(settings, "audit_signing_key_id", "audit-2026-11")
    monkeypatch.setattr(settings, "competition_signing_secret", "ticket-domain-key")
    monkeypatch.setattr(settings, "api_key", "api-domain-key")

    signature, key_id = _audit_signature("a" * 64)

    assert key_id == "audit-2026-11"
    assert signature == hmac.new(
        audit_key.encode("utf-8"), b"a" * 64, hashlib.sha256
    ).hexdigest()


def test_retired_audit_key_ring_verifies_historical_signature(monkeypatch):
    old_key = "retired-audit-domain-key-32-characters"
    digest = "b" * 64
    signature = hmac.new(
        old_key.encode("utf-8"), digest.encode("ascii"), hashlib.sha256
    ).hexdigest()
    monkeypatch.setattr(settings, "audit_signing_key", "n" * 32)
    monkeypatch.setattr(settings, "audit_signing_key_id", "audit-current")
    monkeypatch.setattr(
        settings,
        "audit_verification_keys",
        '{"audit-retired":"retired-audit-domain-key-32-characters"}',
    )

    assert _audit_signature_is_valid(digest, signature, "audit-retired") is True
    assert _audit_signature_is_valid(digest, signature, "unknown") is False


def test_non_production_keeps_demo_security_defaults(monkeypatch):
    _clear_production_markers(monkeypatch)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.delenv("REQUIRE_API_KEY", raising=False)

    configured = Settings()

    assert configured.auth_mode == "disabled"
    assert configured.require_api_key is False


def test_production_requires_oidc_auth_mode(monkeypatch):
    _clear_production_markers(monkeypatch)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("REQUIRE_API_KEY", "true")

    for mode in ("disabled", "api_key", "unsupported"):
        monkeypatch.setenv("AUTH_MODE", mode)
        with pytest.raises(ValidationError, match="AUTH_MODE"):
            Settings()
