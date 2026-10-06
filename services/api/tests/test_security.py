"""Tests for the pilot-stage API key gate (app.security.api_key_gate).

settings.require_api_key defaults to False (see conftest.py), so every other
test file in this suite is implicitly proof that the gate does not change
behaviour for the default/demo configuration. These tests cover the
opt-in path explicitly and restore the default afterwards.
"""
from app.config import settings


def _enable_api_key(key: str = "secret-pilot-key"):
    settings.require_api_key = True
    settings.api_key = key


def _disable_api_key():
    settings.require_api_key = False
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
