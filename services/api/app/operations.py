"""Phase 7 operational controls: request IDs, rate limits, metrics and audit."""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import UTC, datetime
import json
import logging
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
_audit_consecutive_failures = 0
_audit_write_failures_total = 0
_audit_outbox_enqueued_total = 0
_audit_outbox_failures_total = 0

log = logging.getLogger(__name__)


def audit_health_snapshot() -> dict[str, int | str]:
    """Expose audit durability health to readiness without hiding failures.

    A successful audit write clears the transient degraded state; the total
    counter remains monotonic for metrics and incident review.
    """
    with _lock:
        return {
            "status": "degraded" if _audit_consecutive_failures else "ok",
            "consecutive_failures": _audit_consecutive_failures,
            "failures_total": _audit_write_failures_total,
            "outbox_enqueued_total": _audit_outbox_enqueued_total,
            "outbox_failures_total": _audit_outbox_failures_total,
        }


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
        lines.extend([
            "# HELP globalinfra_audit_write_failures_total Audit events that could not be persisted.",
            "# TYPE globalinfra_audit_write_failures_total counter",
            f"globalinfra_audit_write_failures_total {_audit_write_failures_total}",
            "# HELP globalinfra_audit_write_consecutive_failures Consecutive audit persistence failures.",
            "# TYPE globalinfra_audit_write_consecutive_failures gauge",
            f"globalinfra_audit_write_consecutive_failures {_audit_consecutive_failures}",
            "# HELP globalinfra_audit_outbox_enqueued_total Failed primary audit writes durably queued for replay.",
            "# TYPE globalinfra_audit_outbox_enqueued_total counter",
            f"globalinfra_audit_outbox_enqueued_total {_audit_outbox_enqueued_total}",
            "# HELP globalinfra_audit_outbox_failures_total Audit events that could not reach primary storage or the durable outbox.",
            "# TYPE globalinfra_audit_outbox_failures_total counter",
            f"globalinfra_audit_outbox_failures_total {_audit_outbox_failures_total}",
        ])
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


def _enqueue_audit_outbox(event: dict) -> bool:
    """Persist a failed audit write to the configured Redis stream."""
    if not settings.queue_url:
        return False
    try:
        from redis import Redis

        client = Redis.from_url(
            settings.queue_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            decode_responses=True,
        )
        try:
            client.xadd(
                "globalinfra:audit-outbox:v1",
                {
                    "event": json.dumps(
                        event, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "queued_at": datetime.now(UTC).isoformat(),
                },
                maxlen=100_000,
                approximate=True,
            )
        finally:
            client.close()
        return True
    except Exception:
        log.exception("audit outbox enqueue failed event_id=%s", event.get("id"))
        return False


def _write_audit(request: Request, request_id: str, status_code: int, duration_ms: float) -> None:
    global _audit_consecutive_failures, _audit_write_failures_total
    global _audit_outbox_enqueued_total, _audit_outbox_failures_total
    if not settings.audit_mutations or request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    principal = getattr(request.state, "principal", DEMO_PRINCIPAL)
    resource_type, resource_id = _resource(request)
    event = {
        "id": f"AUD-{uuid4().hex}",
        "organization_id": principal.organization_id,
        "actor_id": principal.subject,
        "request_id": request_id,
        "action": f"{request.method} {_path_template(request)}",
        "resource_type": resource_type,
        "resource_id": resource_id,
        "outcome": "SUCCEEDED" if status_code < 400 else "DENIED" if status_code in {401, 403} else "FAILED",
        "detail": {"status_code": status_code, "duration_ms": round(duration_ms, 3)},
    }
    try:
        with SessionLocal() as db:
            db.add(AuditEvent(**event))
            db.commit()
        with _lock:
            _audit_consecutive_failures = 0
    except Exception:
        # The business response has already been produced, but an audit gap is
        # never silent: alert, count it, and make readiness degrade until a
        # later mutation proves that durable audit storage recovered.
        outbox_enqueued = _enqueue_audit_outbox(event)
        with _lock:
            _audit_consecutive_failures += 1
            _audit_write_failures_total += 1
            if outbox_enqueued:
                _audit_outbox_enqueued_total += 1
            else:
                _audit_outbox_failures_total += 1
        log.exception("audit event persistence failed request_id=%s", request_id)


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
