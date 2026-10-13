"""Phase 7 production-pilot APIs.

These endpoints turn mobile observations, external systems, real twin sources
and AI evaluation into governed, tenant-scoped records. Vendor credentials are
never persisted in connector JSON; adapters consume secrets from deployment
configuration when a real connector is enabled.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .i18n import bi
from .models import (
    AIQualityRun, AuditEvent, Case, Connector, ConnectorSyncRun,
    FieldObservation, Identity, Organization, Project, TwinObject, TwinSource, utc_now,
)
from .security import Principal, get_principal, require_project, require_roles

router = APIRouter(tags=["Phase 7 production pilot"])

CONNECTOR_CATALOG = [
    {"type": "primavera_p6", "name": "Primavera P6", "plane": "schedule", "objects": ["WBS", "activity", "baseline", "progress"]},
    {"type": "autodesk_acc", "name": "Autodesk Construction Cloud", "plane": "engineering", "objects": ["document", "issue", "RFI", "model"]},
    {"type": "sharepoint", "name": "Microsoft SharePoint", "plane": "documents", "objects": ["document", "version", "metadata"]},
    {"type": "sap", "name": "SAP / Oracle Commercial", "plane": "commercial", "objects": ["commitment", "purchase order", "invoice", "forecast"]},
    {"type": "arcgis", "name": "ArcGIS / GeoServer", "plane": "geospatial", "objects": ["feature", "layer", "geometry"]},
    {"type": "mqtt", "name": "MQTT / BMS / SCADA", "plane": "telemetry", "objects": ["sensor", "reading", "alarm"]},
]
CONNECTOR_TYPES = {item["type"] for item in CONNECTOR_CATALOG}
TWIN_SOURCE_TYPES = {"IFC", "GLTF", "3D_TILES", "GEOJSON", "WMS", "IOT"}
EVENT_TYPES = {"inspection", "ncr", "rfi", "hse", "progress", "delivery", "commissioning", "maintenance"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _field_row(row: FieldObservation) -> dict:
    return {
        "id": row.id, "client_id": row.client_id, "organization_id": row.organization_id,
        "project_id": row.project_id, "twin_id": row.twin_id, "event_type": row.event_type,
        "severity": row.severity, "description": row.description, "location": row.location,
        "attachments": row.attachments, "reporter_id": row.reporter_id,
        "sync_status": row.sync_status, "case_id": row.case_id,
        "captured_at": row.captured_at.isoformat(), "created_at": row.created_at.isoformat(),
    }


class FieldAttachment(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    media_type: str = Field(max_length=120)
    size: int = Field(ge=0, le=25 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    storage_ref: str | None = Field(default=None, max_length=500)


class FieldObservationIn(BaseModel):
    client_id: str = Field(min_length=8, max_length=96, pattern=r"^[A-Za-z0-9_.:-]+$")
    project_id: int = Field(gt=0)
    twin_id: str | None = Field(default=None, max_length=96)
    event_type: str
    severity: str
    description: str = Field(min_length=4, max_length=10_000)
    location: dict = Field(default_factory=dict)
    attachments: list[FieldAttachment] = Field(default_factory=list, max_length=12)
    captured_at: datetime

    @field_validator("event_type")
    @classmethod
    def valid_event_type(cls, value: str) -> str:
        value = value.lower()
        if value not in EVENT_TYPES:
            raise ValueError("unsupported field event type")
        return value

    @field_validator("severity")
    @classmethod
    def valid_severity(cls, value: str) -> str:
        value = value.upper()
        if value not in SEVERITIES:
            raise ValueError("unsupported severity")
        return value


class FieldSyncIn(BaseModel):
    observations: list[FieldObservationIn] = Field(min_length=1, max_length=100)


def _create_field_observation(payload: FieldObservationIn, db: Session, principal: Principal) -> tuple[FieldObservation, bool]:
    existing = db.scalar(select(FieldObservation).where(FieldObservation.client_id == payload.client_id))
    if existing:
        if existing.organization_id != principal.organization_id:
            raise HTTPException(409, "Client identifier already belongs to another organization")
        return existing, False
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    require_project(principal, payload.project_id)
    if payload.twin_id:
        twin = db.get(TwinObject, payload.twin_id)
        if not twin or twin.project_id != payload.project_id:
            raise HTTPException(422, "Twin ID is not part of the selected project")
    observation_id = f"FO-{uuid4().hex[:16].upper()}"
    case_id = f"CASE-FIELD-{uuid4().hex[:10].upper()}"
    attachments = [item.model_dump() for item in payload.attachments]
    media_ready = all(item.get("storage_ref") for item in attachments) if attachments else True
    row = FieldObservation(
        id=observation_id, client_id=payload.client_id,
        organization_id=principal.organization_id, project_id=payload.project_id,
        twin_id=payload.twin_id, event_type=payload.event_type, severity=payload.severity,
        description=payload.description, location=payload.location, attachments=attachments,
        reporter_id=principal.subject, sync_status="SYNCED" if media_ready else "MEDIA_PENDING",
        case_id=case_id, captured_at=_naive_utc(payload.captured_at),
    )
    case = Case(
        id=case_id, project_id=payload.project_id,
        title=bi(f"Field {payload.event_type}: {payload.description[:90]}"),
        description=bi(payload.description), type=bi(payload.event_type.upper()),
        risk=payload.severity, status="NEW", deadline=bi("To be triaged"),
        source_language=bi("Field mobile"),
        detected_issues=[payload.event_type, *( [payload.twin_id] if payload.twin_id else [] )],
        project_routing_confidence=1.0, routing_status="ROUTED",
    )
    db.add_all([case, row])
    db.commit()
    db.refresh(row)
    return row, True


@router.get("/identity/me")
def identity_me(principal: Principal = Depends(get_principal)):
    return {**principal.as_dict(), "auth_mode": settings.auth_mode, "authorization": "RBAC + project scope"}


@router.post("/identity/register")
def register_identity(
    principal: Principal = Depends(require_roles("viewer", "field_user", "engineer", "project_manager", "organization_admin")),
    db: Session = Depends(get_db),
):
    organization = db.get(Organization, principal.organization_id)
    if not organization:
        organization = Organization(id=principal.organization_id, name=principal.organization_id)
        db.add(organization)
    identity = db.scalar(select(Identity).where(Identity.subject == principal.subject))
    if not identity:
        identity = Identity(
            id=f"ID-{uuid4().hex}", organization_id=principal.organization_id,
            issuer=principal.issuer, subject=principal.subject, display_name=principal.display_name,
            email=principal.email, roles=sorted(principal.roles), project_ids=sorted(principal.project_ids),
        )
        db.add(identity)
    else:
        identity.display_name, identity.email = principal.display_name, principal.email
        identity.roles, identity.project_ids, identity.last_seen_at = sorted(principal.roles), sorted(principal.project_ids), utc_now()
    db.commit()
    return {"status": "REGISTERED", "identity_id": identity.id, **principal.as_dict()}


@router.get("/audit/events")
def audit_events(
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_roles("organization_admin")), db: Session = Depends(get_db),
):
    rows = db.scalars(select(AuditEvent).where(AuditEvent.organization_id == principal.organization_id).order_by(AuditEvent.occurred_at.desc()).limit(limit))
    return [{
        "id": row.id, "actor_id": row.actor_id, "request_id": row.request_id,
        "action": row.action, "resource_type": row.resource_type, "resource_id": row.resource_id,
        "outcome": row.outcome, "detail": row.detail, "occurred_at": row.occurred_at.isoformat(),
    } for row in rows]


@router.post("/field/observations", status_code=201)
def create_field_observation(
    payload: FieldObservationIn,
    principal: Principal = Depends(require_roles("field_user", "engineer", "project_manager")),
    db: Session = Depends(get_db),
):
    row, created = _create_field_observation(payload, db, principal)
    return {**_field_row(row), "created": created}


@router.post("/field/sync")
def sync_field_observations(
    payload: FieldSyncIn,
    principal: Principal = Depends(require_roles("field_user", "engineer", "project_manager")),
    db: Session = Depends(get_db),
):
    results = []
    for observation in payload.observations:
        row, created = _create_field_observation(observation, db, principal)
        results.append({"client_id": row.client_id, "id": row.id, "case_id": row.case_id, "status": row.sync_status, "created": created})
    return {"accepted": len(results), "results": results, "server_time": utc_now().isoformat()}


@router.get("/field/observations")
def field_observations(
    project_id: int | None = None, limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_roles("viewer", "field_user", "engineer", "project_manager")),
    db: Session = Depends(get_db),
):
    stmt = select(FieldObservation).where(FieldObservation.organization_id == principal.organization_id)
    if project_id is not None:
        require_project(principal, project_id)
        stmt = stmt.where(FieldObservation.project_id == project_id)
    elif principal.project_ids:
        stmt = stmt.where(FieldObservation.project_id.in_(principal.project_ids))
    rows = db.scalars(stmt.order_by(FieldObservation.captured_at.desc()).limit(limit))
    return [_field_row(row) for row in rows]


class TwinSourceIn(BaseModel):
    project_id: int = Field(gt=0)
    source_type: str
    name: str = Field(min_length=2, max_length=160)
    uri: str = Field(min_length=4, max_length=500)
    version: str = Field(min_length=1, max_length=80)
    coordinate_reference_system: str | None = Field(default=None, max_length=80)
    checksum: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    metadata: dict = Field(default_factory=dict)

    @field_validator("source_type")
    @classmethod
    def valid_source_type(cls, value: str) -> str:
        value = value.upper()
        if value not in TWIN_SOURCE_TYPES:
            raise ValueError("unsupported twin source type")
        return value

    @field_validator("uri")
    @classmethod
    def safe_uri(cls, value: str) -> str:
        if not value.startswith(("https://", "s3://", "ifc://", "tiles://", "geojson://", "mqtt://")):
            raise ValueError("unsupported source URI scheme")
        return value


def _twin_source_row(row: TwinSource) -> dict:
    return {
        "id": row.id, "project_id": row.project_id, "source_type": row.source_type,
        "name": row.name, "uri": row.uri, "version": row.version,
        "coordinate_reference_system": row.coordinate_reference_system,
        "status": row.status, "checksum": row.checksum, "metadata": row.metadata_json,
        "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
    }


@router.post("/twin/sources", status_code=201)
def register_twin_source(
    payload: TwinSourceIn,
    principal: Principal = Depends(require_roles("engineer", "project_manager", "integration_service")),
    db: Session = Depends(get_db),
):
    require_project(principal, payload.project_id)
    if not db.get(Project, payload.project_id):
        raise HTTPException(404, "Project not found")
    row = TwinSource(
        id=f"TS-{uuid4().hex[:16].upper()}", organization_id=principal.organization_id,
        project_id=payload.project_id, source_type=payload.source_type, name=payload.name,
        uri=payload.uri, version=payload.version,
        coordinate_reference_system=payload.coordinate_reference_system,
        status="REGISTERED", checksum=payload.checksum, metadata_json=payload.metadata,
    )
    db.add(row); db.commit(); db.refresh(row)
    return _twin_source_row(row)


@router.get("/twin/sources")
def twin_sources(
    project_id: int | None = None, principal: Principal = Depends(get_principal), db: Session = Depends(get_db),
):
    stmt = select(TwinSource).where(TwinSource.organization_id == principal.organization_id)
    if project_id is not None:
        require_project(principal, project_id); stmt = stmt.where(TwinSource.project_id == project_id)
    elif principal.project_ids:
        stmt = stmt.where(TwinSource.project_id.in_(principal.project_ids))
    return [_twin_source_row(row) for row in db.scalars(stmt.order_by(TwinSource.created_at.desc()))]


@router.post("/twin/sources/{source_id}/sync")
def sync_twin_source(
    source_id: str, principal: Principal = Depends(require_roles("engineer", "project_manager", "integration_service")),
    db: Session = Depends(get_db),
):
    row = db.get(TwinSource, source_id)
    if not row or row.organization_id != principal.organization_id:
        raise HTTPException(404, "Twin source not found")
    require_project(principal, row.project_id)
    row.status, row.last_synced_at = "SYNCHRONIZED", utc_now()
    db.commit()
    return {**_twin_source_row(row), "contract": "Twin ID + version + checksum preserved"}


class ConnectorIn(BaseModel):
    connector_type: str
    name: str = Field(min_length=2, max_length=160)
    project_id: int | None = Field(default=None, gt=0)
    config: dict = Field(default_factory=dict)

    @field_validator("connector_type")
    @classmethod
    def valid_connector(cls, value: str) -> str:
        if value not in CONNECTOR_TYPES:
            raise ValueError("unsupported connector type")
        return value

    @field_validator("config")
    @classmethod
    def no_secrets(cls, value: dict) -> dict:
        forbidden = {"secret", "password", "token", "api_key", "client_secret"}
        if any(str(key).lower() in forbidden for key in value):
            raise ValueError("credentials must be supplied through deployment secrets, not connector config")
        return value


class SyncPayload(BaseModel):
    records: list[dict] = Field(default_factory=list, max_length=1000)
    cursor: str | None = Field(default=None, max_length=255)


def _connector_row(row: Connector) -> dict:
    return {
        "id": row.id, "project_id": row.project_id, "connector_type": row.connector_type,
        "name": row.name, "status": row.status, "config": row.config,
        "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
    }


@router.get("/integrations/catalog")
def connector_catalog(): return CONNECTOR_CATALOG


@router.post("/integrations/connectors", status_code=201)
def create_connector(
    payload: ConnectorIn,
    principal: Principal = Depends(require_roles("organization_admin", "project_manager", "integration_service")),
    db: Session = Depends(get_db),
):
    if payload.project_id:
        require_project(principal, payload.project_id)
    row = Connector(
        id=f"CON-{uuid4().hex[:16].upper()}", organization_id=principal.organization_id,
        project_id=payload.project_id, connector_type=payload.connector_type,
        name=payload.name, status="CONFIGURED", config=payload.config,
    )
    db.add(row); db.commit(); db.refresh(row)
    return _connector_row(row)


@router.get("/integrations/connectors")
def connectors(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.scalars(select(Connector).where(Connector.organization_id == principal.organization_id).order_by(Connector.created_at.desc()))
    return [_connector_row(row) for row in rows if row.project_id is None or principal.can_access_project(row.project_id)]


def _sync_connector(row: Connector, payload: SyncPayload, db: Session) -> ConnectorSyncRun:
    rejected = sum(1 for record in payload.records if not isinstance(record.get("external_id"), str))
    accepted = len(payload.records) - rejected
    run = ConnectorSyncRun(
        id=f"SYNC-{uuid4().hex[:16].upper()}", connector_id=row.id,
        status="COMPLETED" if rejected == 0 else "COMPLETED_WITH_REJECTIONS",
        cursor=payload.cursor, records_read=len(payload.records), records_written=accepted,
        records_rejected=rejected,
        detail={"canonical_contract": ["external_id", "object_type", "updated_at", "payload"], "secrets_persisted": False},
        completed_at=utc_now(),
    )
    row.status, row.last_sync_at = "ONLINE", utc_now()
    db.add(run); db.commit(); db.refresh(run)
    return run


@router.post("/integrations/connectors/{connector_id}/sync")
def sync_connector(
    connector_id: str, payload: SyncPayload,
    principal: Principal = Depends(require_roles("organization_admin", "project_manager", "integration_service")),
    db: Session = Depends(get_db),
):
    row = db.get(Connector, connector_id)
    if not row or row.organization_id != principal.organization_id:
        raise HTTPException(404, "Connector not found")
    if row.project_id: require_project(principal, row.project_id)
    run = _sync_connector(row, payload, db)
    return {"id": run.id, "connector_id": run.connector_id, "status": run.status, "records_read": run.records_read, "records_written": run.records_written, "records_rejected": run.records_rejected, "detail": run.detail}


@router.post("/integrations/webhooks/{connector_id}")
async def connector_webhook(connector_id: str, request: Request, db: Session = Depends(get_db)):
    if not settings.connector_webhook_secret:
        raise HTTPException(503, "Connector webhook secret is not configured")
    body = await request.body()
    supplied = request.headers.get("x-globalinfra-signature", "")
    expected = hmac.new(settings.connector_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied.removeprefix("sha256="), expected):
        raise HTTPException(401, "Invalid webhook signature")
    row = db.get(Connector, connector_id)
    if not row: raise HTTPException(404, "Connector not found")
    try:
        import json
        data = json.loads(body)
        payload = SyncPayload.model_validate(data)
    except Exception as exc:
        raise HTTPException(422, "Invalid connector payload") from exc
    run = _sync_connector(row, payload, db)
    return {"status": run.status, "sync_run_id": run.id}


class AIQualityIn(BaseModel):
    suite: str = Field(min_length=2, max_length=80)
    model_provider: str = Field(min_length=2, max_length=48)
    model_name: str = Field(min_length=2, max_length=120)
    score: float = Field(ge=0, le=1)
    minimum_score: float = Field(default=0.85, ge=0, le=1)
    metrics: dict = Field(default_factory=dict)
    dataset_version: str = Field(min_length=1, max_length=80)


@router.post("/ai/quality-runs", status_code=201)
def create_quality_run(
    payload: AIQualityIn,
    principal: Principal = Depends(require_roles("engineer", "project_manager", "organization_admin")),
    db: Session = Depends(get_db),
):
    status = "PASSED" if payload.score >= payload.minimum_score else "BLOCKED"
    row = AIQualityRun(
        id=f"EVAL-{uuid4().hex[:16].upper()}", organization_id=principal.organization_id,
        suite=payload.suite, model_provider=payload.model_provider, model_name=payload.model_name,
        status=status, score=payload.score, thresholds={"minimum_score": payload.minimum_score},
        metrics=payload.metrics, dataset_version=payload.dataset_version,
    )
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "status": status, "score": row.score, "release_gate": "OPEN" if status == "PASSED" else "CLOSED"}


@router.get("/ai/quality-runs")
def quality_runs(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.scalars(select(AIQualityRun).where(AIQualityRun.organization_id == principal.organization_id).order_by(AIQualityRun.created_at.desc()).limit(100))
    return [{"id": row.id, "suite": row.suite, "model_provider": row.model_provider, "model_name": row.model_name, "status": row.status, "score": row.score, "thresholds": row.thresholds, "metrics": row.metrics, "dataset_version": row.dataset_version, "created_at": row.created_at.isoformat()} for row in rows]


@router.get("/platform/capabilities")
def platform_capabilities(db: Session = Depends(get_db)):
    counts = {
        "field_observations": db.scalar(select(func.count(FieldObservation.id))) or 0,
        "twin_sources": db.scalar(select(func.count(TwinSource.id))) or 0,
        "connectors": db.scalar(select(func.count(Connector.id))) or 0,
        "ai_quality_runs": db.scalar(select(func.count(AIQualityRun.id))) or 0,
    }
    return {
        "version": "3.0.0", "stage": "PHASE_7_PRODUCTION_PILOT",
        "capabilities": {
            "7.1": "trusted_execution", "7.2": "oidc_rbac_multitenancy_audit",
            "7.3": "offline_field_operations", "7.4": "real_twin_source_registry",
            "7.5": "enterprise_connector_plane", "7.6": "ai_quality_release_gate",
            "7.7": "observability_security_resilience",
        },
        "counts": counts,
    }
