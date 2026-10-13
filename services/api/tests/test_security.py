"""Tests for the three-mode identity boundary (app.security.api_key_gate).

settings.require_api_key defaults to False (see conftest.py), so every other
test file in this suite is implicitly proof that the gate does not change
behaviour for the default/demo configuration. These tests cover the
opt-in path explicitly and restore the default afterwards.
"""
from app.config import settings
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
