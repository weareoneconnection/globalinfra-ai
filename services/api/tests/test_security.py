"""Tests for the three-mode identity boundary (app.security.api_key_gate).

settings.require_api_key defaults to False (see conftest.py), so every other
test file in this suite is implicitly proof that the gate does not change
behaviour for the default/demo configuration. These tests cover the
opt-in path explicitly and restore the default afterwards.
"""
from app.config import settings
from app.security import Principal, _service_principal
import jwt
import time
from cryptography.hazmat.primitives.asymmetric import rsa


def _enable_api_key(key: str = "secret-pilot-key"):
    settings.require_api_key = True
    settings.api_key = key


def _disable_api_key():
    settings.require_api_key = False
    settings.auth_mode = "disabled"
    settings.api_key = ""


def test_gate_disabled_by_default_allows_unauthenticated_requests(client):
    assert settings.require_api_key is False
    r = client.get("/projects")
    assert r.status_code == 200


def test_gate_blocks_requests_without_a_key_once_enabled(client):
    _enable_api_key()
    try:
        r = client.get("/projects")
        assert r.status_code == 401
    finally:
        _disable_api_key()


def test_gate_fails_closed_when_enabled_without_a_configured_key(client):
    settings.require_api_key = True
    settings.api_key = ""
    try:
        r = client.get("/projects")
        assert r.status_code == 503
        assert "not configured" in r.json()["detail"]
    finally:
        _disable_api_key()


def test_gate_blocks_requests_with_the_wrong_key(client):
    _enable_api_key()
    try:
        r = client.get("/projects", headers={"X-API-Key": "wrong-key"})
        assert r.status_code == 401
    finally:
        _disable_api_key()


def test_gate_allows_requests_with_the_correct_x_api_key_header(client):
    _enable_api_key()
    try:
        r = client.get("/projects", headers={"X-API-Key": "secret-pilot-key"})
        assert r.status_code == 200
    finally:
        _disable_api_key()


def test_gate_allows_requests_with_the_correct_bearer_token(client):
    _enable_api_key()
    try:
        r = client.get("/projects", headers={"Authorization": "Bearer secret-pilot-key"})
        assert r.status_code == 200
    finally:
        _disable_api_key()


def test_gate_leaves_health_check_reachable_even_when_enabled(client):
    # Orchestrators (Docker/Kubernetes probes, load balancers) must be able
    # to reach /health without a credential.
    _enable_api_key()
    try:
        r = client.get("/health")
        assert r.status_code == 200
    finally:
        _disable_api_key()


def test_empty_oidc_project_claim_does_not_grant_every_project():
    viewer = Principal(
        subject="viewer-without-projects",
        organization_id="org-7",
        roles=frozenset({"viewer"}),
        project_ids=frozenset(),
        issuer="https://identity.example.test",
    )
    administrator = Principal(
        subject="org-admin",
        organization_id="org-7",
        roles=frozenset({"organization_admin"}),
        project_ids=frozenset(),
        issuer="https://identity.example.test",
    )
    service = Principal(
        subject="service:web",
        organization_id="org-7",
        roles=frozenset({"viewer"}),
        project_ids=frozenset(),
        issuer="service-key",
    )

    assert viewer.can_access_project(1) is False
    assert administrator.can_access_project(1) is True
    assert service.can_access_project(1) is True


def test_web_service_principal_cannot_impersonate_business_roles():
    principal = _service_principal()

    assert principal.roles == frozenset({"viewer", "integration_service"})
    assert not principal.roles.intersection(
        {"field_user", "engineer", "project_manager", "hse_manager", "approver", "verifier"}
    )


def test_service_credential_cannot_approve_or_create_business_data(client):
    settings.auth_mode = "oidc"
    settings.require_api_key = True
    settings.api_key = "read-only-web-service-key"
    headers = {"X-API-Key": settings.api_key}
    try:
        approval = client.post("/approvals/1/approve", headers=headers)
        intake = client.post(
            "/intake/text",
            headers=headers,
            json={"text": "Create a new owner-notice case."},
        )
        assert approval.status_code == 403
        assert intake.status_code == 403
    finally:
        _disable_api_key()


def test_oidc_mode_validates_claims_and_enforces_roles(client, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    class SigningKey:
        key = public_key

    class Jwks:
        def get_signing_key_from_jwt(self, _token):
            return SigningKey()

    monkeypatch.setattr("app.security._jwks_client", lambda: Jwks())
    settings.auth_mode = "oidc"
    settings.require_api_key = False
    settings.oidc_issuer = "https://identity.example.test"
    settings.oidc_audience = "api://globalinfra"
    now = int(time.time())
    token = jwt.encode({
        "sub": "user-7", "iss": settings.oidc_issuer, "aud": settings.oidc_audience,
        "iat": now, "exp": now + 600,
        "name": "Project Viewer", "org_id": "org-7", "roles": ["viewer"], "projects": [1],
    }, private_key, algorithm="RS256", headers={"kid": "test-key"})
    try:
        identity = client.get("/identity/me", headers={"Authorization": f"Bearer {token}"})
        assert identity.status_code == 200
        assert identity.json()["organization_id"] == "org-7"
        assert identity.json()["project_ids"] == [1]

        forbidden = client.post("/field/observations", headers={"Authorization": f"Bearer {token}"}, json={})
        assert forbidden.status_code == 403
    finally:
        _disable_api_key()
