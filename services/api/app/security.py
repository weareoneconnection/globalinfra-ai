"""Pilot-stage API authentication gate.

This is an intentionally small, honest step: a single shared-secret API key
checked on every request, used to gate access before an environment is
wired up to a real identity provider. It is **not** SSO/OIDC/SAML, MFA or
per-user/per-tenant authorization (see docs/SECURITY.md "Production
backlog" for what still has to be built for that). What it does give a
pilot deployment, for free and without touching route code, is: the API is
no longer reachable by anyone who can see the URL once
``REQUIRE_API_KEY=true`` is set.

Disabled by default (``require_api_key=False``) so the V1.0 competition/demo
experience — including every existing route and test — is unaffected.
"""
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

from .config import settings

# Health checks must stay reachable without a key so container
# orchestrators (Docker/Kubernetes liveness & readiness probes, load
# balancer health checks) can probe the service before/without credentials.
EXEMPT_PATHS = {"/health"}


def _extract_key(request: Request) -> str | None:
    header_key = request.headers.get("x-api-key")
    if header_key:
        return header_key
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[len("bearer "):].strip()
    return None


async def api_key_gate(request: Request, call_next):
    """ASGI middleware enforcing ``settings.api_key`` when
    ``settings.require_api_key`` is on. Registered unconditionally in
    ``main.py``; the setting is re-read per request so tests/deployments can
    flip it without restarting the process."""
    if settings.require_api_key and request.url.path not in EXEMPT_PATHS:
        if not settings.api_key:
            return JSONResponse(status_code=503, content={"detail": "API authentication is enabled but not configured"})
        provided = _extract_key(request)
        if not provided or not secrets.compare_digest(provided, settings.api_key):
            return JSONResponse(status_code=401, content={"detail": "Missing or invalid API key"})
    return await call_next(request)
