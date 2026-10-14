"""Phase 7 operational controls: request IDs, rate limits, metrics and audit."""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from threading import Lock
from time import monotonic, perf_counter
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .config import settings
from .database import SessionLocal
from .models import AuditEvent
from .security import DEMO_PRINCIPAL

_lock = Lock()
_requests = Counter()
_latency_ms = Counter()
_rate_windows: dict[str, deque[float]] = defaultdict(deque)


def metrics_response() -> PlainTextResponse:
    with _lock:
        lines = [
            "# HELP globalinfra_http_requests_total HTTP requests by method, path and status.",
            "# TYPE globalinfra_http_requests_total counter",
        ]
        for (method, path, status), count in sorted(_requests.items()):
            lines.append(f'globalinfra_http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}')
        lines.extend([
            "# HELP globalinfra_http_request_duration_ms_total Aggregate request latency.",
            "# TYPE globalinfra_http_request_duration_ms_total counter",
        ])
        for (method, path), value in sorted(_latency_ms.items()):
            lines.append(f'globalinfra_http_request_duration_ms_total{{method="{method}",path="{path}"}} {value:.3f}')
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


def _path_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


def _resource(request: Request) -> tuple[str, str | None]:
    parts = [part for part in request.url.path.split("/") if part]
    return (parts[0] if parts else "root", parts[1] if len(parts) > 1 else None)


def _over_limit(request: Request) -> bool:
    limit = max(1, settings.rate_limit_per_minute)
    host = request.client.host if request.client else "unknown"
    now = monotonic()
    with _lock:
        window = _rate_windows[host]
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= limit:
            return True
        window.append(now)
    return False


def _write_audit(request: Request, request_id: str, status_code: int, duration_ms: float) -> None:
    if not settings.audit_mutations or request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    principal = getattr(request.state, "principal", DEMO_PRINCIPAL)
    resource_type, resource_id = _resource(request)
    try:
        with SessionLocal() as db:
            db.add(AuditEvent(
                id=f"AUD-{uuid4().hex}", organization_id=principal.organization_id,
                actor_id=principal.subject, request_id=request_id,
                action=f"{request.method} {_path_template(request)}",
                resource_type=resource_type, resource_id=resource_id,
                outcome="SUCCEEDED" if status_code < 400 else "DENIED" if status_code in {401, 403} else "FAILED",
                detail={"status_code": status_code, "duration_ms": round(duration_ms, 3)},
            ))
            db.commit()
    except Exception:
        # Audit storage must never corrupt the business response. Production
        # monitoring detects missing audit writes through readiness telemetry.
        return


async def production_controls(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid4().hex
    request.state.request_id = request_id
    if request.url.path not in {"/health", "/livez", "/readyz", "/metrics"} and _over_limit(request):
        response = JSONResponse({"detail": "Rate limit exceeded", "request_id": request_id}, status_code=429)
        response.headers["Retry-After"] = "60"
        response.headers["X-Request-ID"] = request_id
        return response
    started = perf_counter()
    response = await call_next(request)
    duration_ms = (perf_counter() - started) * 1000
    path = _path_template(request)
    with _lock:
        _requests[(request.method, path, str(response.status_code))] += 1
        _latency_ms[(request.method, path)] += duration_ms
    response.headers["X-Request-ID"] = request_id
    _write_audit(request, request_id, response.status_code, duration_ms)
    return response
