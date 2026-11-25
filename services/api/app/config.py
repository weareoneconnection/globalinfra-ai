import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


VALID_AUTH_MODES = frozenset({"disabled", "api_key", "oidc"})
PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().upper()
    return any(
        marker in normalized
        for marker in (
            "REPLACE_",
            "CHANGEME",
            "CHANGE_ME",
            "EXAMPLE_ONLY",
            "DB_USER",
            "DB_PASSWORD",
            "DB_HOST",
            "DB_NAME",
            "REDIS_HOST",
            "EXAMPLE.COM",
            "EXAMPLE.TEST",
        )
    )


def _is_configured(value: str) -> bool:
    return bool(value.strip()) and not _is_placeholder(value)


def _valid_ed25519_public_key(value: str) -> bool:
    if not value.strip():
        return False
    try:
        loaded = serialization.load_pem_public_key(
            value.replace("\\n", "\n").strip().encode("utf-8") + b"\n"
        )
    except (TypeError, ValueError):
        return False
    return isinstance(loaded, Ed25519PublicKey)


def _valid_durable_redis_url(value: str) -> bool:
    if not _is_configured(value):
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return (
        parsed.scheme in {"redis", "rediss"}
        and bool(parsed.hostname)
        and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
    )


def is_production_environment(
    environment: str | None = None,
    railway_environment: str | None = None,
) -> bool:
    """Return whether any supported deployment marker identifies production."""
    values = [environment, railway_environment]
    values.extend(os.getenv(name) for name in ("ENV", "APP_ENV"))
    values.extend(
        os.getenv(name)
        for name in ("RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT")
    )
    return any(
        isinstance(value, str) and value.strip().lower() in PRODUCTION_ENVIRONMENTS
        for value in values
    )


class Settings(BaseSettings):
    database_url: str = "sqlite:///./globalinfra.db"
    redis_url: str = "redis://localhost:6379/0"
    llm_mode: str = "mock"
    openai_compat_base_url: str = "https://api.openai.com/v1"
    openai_compat_api_key: str = ""
    openai_compat_model: str = "gpt-5.6-mini"
    local_llm_base_url: str = "http://host.docker.internal:11434/v1"
    local_llm_api_key: str = ""
    local_llm_model: str = "qwen3:8b"
    llm_preferred_provider: str = "local"
    llm_cloud_fallback_enabled: bool = True
    # Pilot-stage auth gate (see app.security): a single shared-secret API
    # key, *not* a replacement for enterprise SSO/OIDC. Off by default so
    # the V1.0 competition/demo flow is unaffected; a pilot deployment can
    # turn it on without any code change.
    require_api_key: bool = False
    api_key: str = ""
    cors_origins: str = "http://localhost:3000"
    max_upload_bytes: int = 10 * 1024 * 1024
    # Phase 7 production-pilot controls. ``disabled`` preserves the public
    # competition demo; production pilots should use ``oidc``.
    auth_mode: str = "disabled"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_roles_claim: str = "roles"
    oidc_organization_claim: str = "org_id"
    oidc_projects_claim: str = "projects"
    default_organization_id: str = "globalinfra-demo"
    audit_mutations: bool = True
    rate_limit_per_minute: int = 180
    connector_webhook_secret: str = ""
    object_storage_endpoint: str = ""
    object_storage_bucket: str = "globalinfra-field"
    telemetry_stale_seconds: int = 300
    # V6 competition and governance controls. Sandbox role tickets are
    # process-local when no secret is configured, so a production deployment
    # must provide COMPETITION_SIGNING_SECRET through its secret manager.
    competition_v6_enabled: bool = True
    competition_session_ttl_minutes: int = 30
    competition_signing_secret: str = ""
    # Dedicated key for approval/execution/verification/closure receipts.
    # It must not share a trust domain with judge tickets or release evidence.
    audit_signing_key: str = ""
    audit_signing_key_id: str = "primary-v1"
    # JSON object of retired key IDs to verification-only secrets. This lets
    # historical receipts remain verifiable after the active key rotates.
    audit_verification_keys: str = "{}"
    # Production receives only the Ed25519 public verification key. The
    # private key stays in CI/KMS. ``evidence_signing_key`` is a legacy HMAC
    # compatibility path and is rejected in production unless explicitly
    # opted in; it must never be confused with the sandbox ticket secret.
    evidence_verification_public_key: str = ""
    evidence_signing_key: str = ""
    evidence_allow_legacy_hmac: bool = False
    release_evidence_path: str = ""
    deployment_commit_sha: str = Field(
        default="",
        validation_alias=AliasChoices("GIT_COMMIT_SHA", "RAILWAY_GIT_COMMIT_SHA"),
    )
    sod_enforced: bool = True
    evidence_bundle_required: bool = True
    sandbox_mode: bool = True
    # Explicit, temporary finals profile.  This never promotes the platform
    # readiness/evidence endpoints to READY; it only lets a managed Postgres
    # deployment start and serve synthetic competition data while enterprise
    # identity, queue, object storage and external signing are being wired.
    competition_fast_launch: bool = False
    # Production-readiness metadata is exposed as policy, not as a claim that
    # an external service is configured. Empty endpoints remain NOT_CONFIGURED.
    queue_url: str = ""
    data_residency_region: str = ""
    backup_retention_days: int = 30
    recovery_point_objective_minutes: int = 15
    recovery_time_objective_minutes: int = 60
    country_pack_review_max_age_days: int = 180
    environment: str = Field(
        default="", validation_alias=AliasChoices("ENV", "APP_ENV")
    )
    railway_environment: str = Field(
        default="",
        validation_alias=AliasChoices(
            "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT"
        ),
    )
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_production_security(self):
        if not is_production_environment(self.environment, self.railway_environment):
            return self

        mode = self.auth_mode.strip().lower()
        if self.competition_fast_launch:
            errors = []
            if mode not in VALID_AUTH_MODES:
                errors.append("AUTH_MODE must be disabled, api_key or oidc")
            if mode == "disabled" and self.require_api_key:
                errors.append(
                    "REQUIRE_API_KEY must be false when the fast-launch AUTH_MODE is disabled"
                )
            if mode == "api_key" and (
                len(self.api_key) < 32 or _is_placeholder(self.api_key)
            ):
                errors.append(
                    "API_KEY must be a non-placeholder 32-character secret in api_key mode"
                )
            if mode == "oidc" and not all(
                _is_configured(value)
                for value in (self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url)
            ):
                errors.append(
                    "OIDC_ISSUER, OIDC_AUDIENCE and OIDC_JWKS_URL are required in oidc mode"
                )
            if self.database_url.startswith("sqlite") or _is_placeholder(
                self.database_url
            ):
                errors.append("DATABASE_URL must still use a managed production database")
            if not self.competition_v6_enabled or not self.sandbox_mode:
                errors.append(
                    "COMPETITION_V6_ENABLED and SANDBOX_MODE must remain true in fast-launch mode"
                )
            if not self.sod_enforced:
                errors.append("SOD_ENFORCED must remain true in fast-launch mode")
            if not self.audit_mutations:
                errors.append("AUDIT_MUTATIONS must remain true in fast-launch mode")
            if self.evidence_bundle_required:
                errors.append(
                    "EVIDENCE_BUNDLE_REQUIRED must be false so missing release proof stays visibly UNVERIFIED"
                )
            if os.getenv("EVIDENCE_SIGNING_PRIVATE_KEY", "").strip():
                errors.append(
                    "EVIDENCE_SIGNING_PRIVATE_KEY must remain in CI/KMS and must not be present in the API runtime"
                )
            if errors:
                raise ValueError(
                    "Competition fast-launch configuration invalid: "
                    + "; ".join(errors)
                )
            return self

        errors = []
        if mode != "oidc":
            errors.append(
                "AUTH_MODE must be oidc in production; shared API keys cannot represent separated human actors"
            )
        if self.require_api_key is not True:
            errors.append("REQUIRE_API_KEY must be explicitly set to true")
        if len(self.api_key) < 32 or _is_placeholder(self.api_key):
            errors.append(
                "API_KEY must be a non-placeholder secret containing at least 32 characters"
            )
        if not _is_configured(
            self.default_organization_id
        ) or self.default_organization_id in {
            "globalinfra-demo",
            "MIGRATION_REVIEW_REQUIRED",
        }:
            errors.append("DEFAULT_ORGANIZATION_ID must be an explicit tenant identifier")
        if mode == "oidc" and not all(
            _is_configured(value)
            for value in (self.oidc_issuer, self.oidc_audience, self.oidc_jwks_url)
        ):
            errors.append(
                "OIDC_ISSUER, OIDC_AUDIENCE and OIDC_JWKS_URL must be non-placeholder values"
            )
        if self.sod_enforced is not True:
            errors.append("SOD_ENFORCED must be true")
        if self.database_url.startswith("sqlite") or _is_placeholder(
            self.database_url
        ):
            errors.append("DATABASE_URL must use a production database")
        if not _is_configured(self.data_residency_region):
            errors.append("DATA_RESIDENCY_REGION must name the approved region")
        if not _is_configured(self.object_storage_endpoint):
            errors.append("OBJECT_STORAGE_ENDPOINT must be configured")
        if not _valid_durable_redis_url(self.queue_url):
            errors.append(
                "QUEUE_URL must point to a non-local durable Redis stream for the audit outbox"
            )
        if (
            (self.sod_enforced or (self.competition_v6_enabled and self.sandbox_mode))
            and (
                len(self.competition_signing_secret) < 32
                or _is_placeholder(self.competition_signing_secret)
            )
        ):
            errors.append(
                "COMPETITION_SIGNING_SECRET must be a non-placeholder secret containing at least 32 characters"
            )
        if self.competition_signing_secret == self.api_key:
            errors.append("COMPETITION_SIGNING_SECRET must be separated from API_KEY")
        if self.sod_enforced and (
            len(self.audit_signing_key) < 32
            or _is_placeholder(self.audit_signing_key)
        ):
            errors.append(
                "AUDIT_SIGNING_KEY must be a non-placeholder secret containing at least 32 characters"
            )
        if self.audit_signing_key and self.audit_signing_key in {
            self.api_key,
            self.competition_signing_secret,
        }:
            errors.append(
                "AUDIT_SIGNING_KEY must be separated from API_KEY and COMPETITION_SIGNING_SECRET"
            )
        if self.sod_enforced and (
            not _is_configured(self.audit_signing_key_id)
            or self.audit_signing_key_id in {"environment", "default", "primary-v1"}
        ):
            errors.append(
                "AUDIT_SIGNING_KEY_ID must identify the active versioned audit key"
            )
        try:
            audit_key_ring = json.loads(self.audit_verification_keys or "{}")
        except (TypeError, ValueError):
            audit_key_ring = None
        if not isinstance(audit_key_ring, dict) or any(
            not isinstance(key_id, str)
            or not isinstance(secret, str)
            or len(secret) < 32
            or _is_placeholder(secret)
            for key_id, secret in (audit_key_ring or {}).items()
        ):
            errors.append(
                "AUDIT_VERIFICATION_KEYS must be a JSON object of key IDs to non-placeholder secrets"
            )
        elif self.audit_signing_key_id in audit_key_ring:
            errors.append(
                "AUDIT_VERIFICATION_KEYS must contain retired keys only, not the active AUDIT_SIGNING_KEY_ID"
            )
        if self.evidence_bundle_required:
            public_key_supplied = bool(self.evidence_verification_public_key.strip())
            public_key_valid = _valid_ed25519_public_key(
                self.evidence_verification_public_key
            )
            legacy_hmac_valid = (
                self.evidence_allow_legacy_hmac
                and len(self.evidence_signing_key) >= 32
                and not _is_placeholder(self.evidence_signing_key)
            )
            if public_key_supplied and not public_key_valid:
                errors.append(
                    "EVIDENCE_VERIFICATION_PUBLIC_KEY must be a valid Ed25519 PEM public key"
                )
            elif not public_key_valid and not legacy_hmac_valid:
                errors.append(
                    "EVIDENCE_VERIFICATION_PUBLIC_KEY is required; legacy HMAC needs "
                    "EVIDENCE_ALLOW_LEGACY_HMAC=true and a 32-character EVIDENCE_SIGNING_KEY"
                )
            if os.getenv("EVIDENCE_SIGNING_PRIVATE_KEY", "").strip():
                errors.append(
                    "EVIDENCE_SIGNING_PRIVATE_KEY must remain in CI/KMS and must not be present in the API runtime"
                )
            if legacy_hmac_valid and self.evidence_signing_key in {
                self.api_key,
                self.competition_signing_secret,
                self.audit_signing_key,
            }:
                errors.append(
                    "Legacy EVIDENCE_SIGNING_KEY must be separated from API_KEY, "
                    "COMPETITION_SIGNING_SECRET and AUDIT_SIGNING_KEY"
                )
        if self.evidence_bundle_required and not self.release_evidence_path.strip():
            errors.append(
                "RELEASE_EVIDENCE_PATH must point to the read-only CI artifact when evidence is required"
            )
        elif self.evidence_bundle_required and not Path(self.release_evidence_path).is_file():
            errors.append(
                "RELEASE_EVIDENCE_PATH must exist before a production instance starts"
            )
        if self.evidence_bundle_required and not re.fullmatch(
            r"[0-9a-fA-F]{40,64}", self.deployment_commit_sha.strip()
        ):
            errors.append(
                "GIT_COMMIT_SHA or RAILWAY_GIT_COMMIT_SHA must be a full hexadecimal source commit"
            )
        if errors:
            raise ValueError("Production security configuration invalid: " + "; ".join(errors))
        return self

    @property
    def allowed_origins(self) -> list[str]:
        """Return an explicit CORS allowlist; wildcard origins are rejected."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip() and origin.strip() != "*"]

    @property
    def release_evidence_verifier_configured(self) -> bool:
        return _valid_ed25519_public_key(
            self.evidence_verification_public_key
        ) or (
            self.evidence_allow_legacy_hmac
            and len(self.evidence_signing_key) >= 32
            and not _is_placeholder(self.evidence_signing_key)
        )

    @property
    def durable_audit_outbox_configured(self) -> bool:
        return _valid_durable_redis_url(self.queue_url)

    @property
    def deployment_profile(self) -> str:
        if self.competition_fast_launch:
            return "competition_fast_launch"
        if is_production_environment(self.environment, self.railway_environment):
            return "production_strict"
        return "development"

settings = Settings()
