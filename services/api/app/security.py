"""Authentication and authorization for demo, pilot API-key and OIDC modes."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import settings

try:
    import jwt
    from jwt import PyJWKClient
except ImportError:  # pragma: no cover - only a misconfigured OIDC image.
    jwt = None
    PyJWKClient = None

EXEMPT_PATHS = {"/health", "/livez", "/readyz", "/metrics"}
VALID_ROLES = {
    "platform_admin", "organization_admin", "project_manager", "engineer",
    "field_user", "approver", "verifier", "viewer", "integration_service",
}


@dataclass(frozen=True)
class Principal:
    subject: str
    organization_id: str
    roles: frozenset[str]
    project_ids: frozenset[int]
    display_name: str = ""
    email: str | None = None
    issuer: str = "demo"

    def can_access_project(self, project_id: int) -> bool:
        return "platform_admin" in self.roles or not self.project_ids or project_id in self.project_ids

    def as_dict(self) -> dict:
        return {
            "subject": self.subject, "organization_id": self.organization_id,
            "roles": sorted(self.roles), "project_ids": sorted(self.project_ids),
            "display_name": self.display_name, "email": self.email, "issuer": self.issuer,
        }


DEMO_PRINCIPAL = Principal(
    subject="demo:operator", organization_id="globalinfra-demo",
    roles=frozenset(VALID_ROLES), project_ids=frozenset(), display_name="Demo Operator",
)


def _service_principal() -> Principal:
    return Principal(
        subject="service:web", organization_id=settings.default_organization_id,
        roles=frozenset({"viewer", "field_user", "engineer", "project_manager", "approver", "verifier", "integration_service"}),
        project_ids=frozenset(), display_name="GlobalInfra Web Service", issuer="service-key",
    )


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else None


def _extract_api_key(request: Request) -> str | None:
    return request.headers.get("x-api-key") or _extract_bearer(request)


@lru_cache(maxsize=1)
def _jwks_client():
    if PyJWKClient is None:
        raise RuntimeError("PyJWT cryptography support is required for OIDC mode")
    url = settings.oidc_jwks_url or f"{settings.oidc_issuer.rstrip('/')}/.well-known/jwks.json"
    return PyJWKClient(url, cache_keys=True, lifespan=300)


def _list_claim(payload: dict, name: str) -> list:
    value = payload.get(name, [])
    if isinstance(value, str):
        return [part for part in value.replace(",", " ").split() if part]
    return value if isinstance(value, list) else []


def _oidc_principal(token: str) -> Principal:
    if jwt is None:
        raise RuntimeError("OIDC mode is configured but PyJWT is not installed")
    signing_key = _jwks_client().get_signing_key_from_jwt(token).key
    payload = jwt.decode(
        token, signing_key, algorithms=["RS256", "RS384", "RS512", "ES256"],
        audience=settings.oidc_audience, issuer=settings.oidc_issuer,
        options={"require": ["exp", "iat", "sub"], "verify_aud": bool(settings.oidc_audience)},
    )
    roles = frozenset(str(role) for role in _list_claim(payload, settings.oidc_roles_claim) if role in VALID_ROLES)
    project_ids = frozenset(int(value) for value in _list_claim(payload, settings.oidc_projects_claim) if str(value).isdigit())
    organization_id = str(payload.get(settings.oidc_organization_claim) or "")
    if not organization_id or not roles:
        raise ValueError("OIDC token is missing organization or recognized roles")
    return Principal(
        subject=str(payload["sub"]), organization_id=organization_id, roles=roles,
        project_ids=project_ids,
        display_name=str(payload.get("name") or payload.get("preferred_username") or payload["sub"]),
        email=payload.get("email"), issuer=str(payload.get("iss") or settings.oidc_issuer),
    )


async def api_key_gate(request: Request, call_next):
    """Compatibility name retained while the gate now supports three modes."""
    mode = settings.auth_mode.lower().strip()
    if settings.require_api_key and mode == "disabled":
        mode = "api_key"
    if request.url.path in EXEMPT_PATHS:
        request.state.principal = DEMO_PRINCIPAL
        return await call_next(request)
    try:
        if mode == "disabled":
            principal = DEMO_PRINCIPAL
        elif mode == "api_key":
            provided = _extract_api_key(request)
            if not settings.api_key:
                return JSONResponse(status_code=503, content={"detail": "API authentication is enabled but not configured"})
            import secrets
            if not provided or not secrets.compare_digest(provided, settings.api_key):
                return JSONResponse(status_code=401, content={"detail": "Missing or invalid API key"})
            principal = _service_principal()
        elif mode == "oidc":
            token = _extract_bearer(request)
            service_key = request.headers.get("x-api-key")
            if token:
                principal = _oidc_principal(token)
            elif settings.api_key and service_key:
                import secrets
                if not secrets.compare_digest(service_key, settings.api_key):
                    return JSONResponse(status_code=401, content={"detail": "Invalid service credential"})
                principal = _service_principal()
            else:
                return JSONResponse(status_code=401, content={"detail": "Bearer token or trusted service credential required"})
        else:
            return JSONResponse(status_code=503, content={"detail": f"Unsupported AUTH_MODE: {mode}"})
    except Exception:
        return JSONResponse(status_code=401, content={"detail": "Invalid or expired identity token"})
    request.state.principal = principal
    return await call_next(request)


def get_principal(request: Request) -> Principal:
    return getattr(request.state, "principal", DEMO_PRINCIPAL)


def require_roles(*allowed: str) -> Callable:
    invalid = set(allowed) - VALID_ROLES
    if invalid:
        raise ValueError(f"Unknown roles: {sorted(invalid)}")

    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if "platform_admin" not in principal.roles and not principal.roles.intersection(allowed):
            raise HTTPException(403, "This action is not permitted for the current role")
        return principal

    return dependency


def require_project(principal: Principal, project_id: int) -> None:
    if not principal.can_access_project(project_id):
        raise HTTPException(403, "Project is outside the current identity scope")
