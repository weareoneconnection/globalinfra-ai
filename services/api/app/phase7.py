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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .competition import current_release_evidence, release_validation_checks
from .database import get_db
from .field_ai import analyze_reports, classify_report, prepare_case, report_payload
from .field_media import verify_attachment
from .i18n import bi, get_lang, localize
from .models import (
    AIQualityRun, AuditEvent, Case, Connector, ConnectorSyncRun,
    FieldObservation, Identity, IngestionReceipt, Organization, Project, TwinModelVersion,
    PilotMeasurement, TwinObject, TwinSource, TwinTelemetryReading, utc_now,
)
from .security import Principal, get_principal, require_project, require_roles
from .ingestion import receipt_payload, record_ingestion_receipt
from .operations import audit_health_snapshot

router = APIRouter(tags=["Phase 7 production pilot"])

CONNECTOR_CATALOG = [
    {"type": "primavera_p6", "name": "Primavera P6", "plane": "schedule", "objects": ["WBS", "activity", "baseline", "progress"], "implementation_status": "SANDBOX_CONTRACT", "contract_version": "globalinfra.p6.activity.v1"},
    {"type": "autodesk_acc", "name": "Autodesk Construction Cloud", "plane": "engineering", "objects": ["document", "issue", "RFI", "model"]},
    {"type": "sharepoint", "name": "Microsoft SharePoint", "plane": "documents", "objects": ["document", "version", "metadata"]},
    {"type": "sap", "name": "SAP / Oracle Commercial", "plane": "commercial", "objects": ["commitment", "purchase order", "invoice", "forecast"]},
    {"type": "arcgis", "name": "ArcGIS / GeoServer", "plane": "geospatial", "objects": ["feature", "layer", "geometry"]},
    {"type": "mqtt", "name": "MQTT / BMS / SCADA", "plane": "telemetry", "objects": ["sensor", "reading", "alarm"]},
]
CONNECTOR_TYPES = {item["type"] for item in CONNECTOR_CATALOG}
TWIN_SOURCE_TYPES = {"IFC", "GLTF", "3D_TILES", "GEOJSON", "WMS", "IOT"}
EVENT_TYPES = {"observation", "inspection", "ncr", "rfi", "hse", "progress", "delivery", "commissioning", "maintenance"}
# AUTO: the reporter leaves the risk to the AI assessment.
SEVERITIES = {"AUTO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}


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
        "analysis_status": row.analysis_status, "ai_risk": row.ai_risk,
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


def _field_receipt(db: Session, row: FieldObservation) -> IngestionReceipt | None:
    return db.scalar(
        select(IngestionReceipt)
        .where(IngestionReceipt.channel == "event_work_order", IngestionReceipt.target_id == row.id)
        .order_by(IngestionReceipt.created_at.desc())
    )


def _create_field_observation(payload: FieldObservationIn, db: Session, principal: Principal) -> tuple[FieldObservation, bool, IngestionReceipt | None]:
    existing = db.scalar(select(FieldObservation).where(FieldObservation.client_id == payload.client_id))
    if existing:
        if existing.organization_id != principal.organization_id:
            raise HTTPException(409, "Client identifier already belongs to another organization")
        return existing, False, _field_receipt(db, existing)
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    require_project(principal, payload.project_id, db)
    if payload.twin_id:
        twin = db.get(TwinObject, payload.twin_id)
        if not twin or twin.project_id != payload.project_id:
            raise HTTPException(422, "Twin ID is not part of the selected project")
    for attachment in payload.attachments:
        if attachment.storage_ref:
            verify_attachment(
                db,
                principal.organization_id,
                payload.project_id,
                attachment.sha256,
                attachment.storage_ref,
            )
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
        id=case_id, organization_id=principal.organization_id,
        project_id=payload.project_id,
        title=bi(f"Field {payload.event_type}: {payload.description[:90]}"),
        description=bi(payload.description), type=bi(payload.event_type.upper()),
        risk=payload.severity, status="NEW", deadline=bi("To be triaged"),
        source_language=bi("Field mobile"),
        detected_issues=[payload.event_type, *( [payload.twin_id] if payload.twin_id else [] )],
        project_routing_confidence=1.0, routing_status="ROUTED",
    )
    db.add_all([case, row])
    text, result = classify_report(payload.event_type, payload.description, payload.twin_id)
    prepare_case(db, case, row, text, result)
    receipt = record_ingestion_receipt(
        db, organization_id=principal.organization_id, project_id=payload.project_id,
        channel="event_work_order", source_type="mobile_field",
        status="SYNCED" if media_ready else "MEDIA_PENDING",
        target_type="FieldObservation", target_id=observation_id,
        checksum=hashlib.sha256(f"{payload.client_id}:{payload.description}".encode()).hexdigest(),
        validation_summary={
            "schema": "valid", "twin_linked": bool(payload.twin_id),
            "media_ready": media_ready, "severity": payload.severity,
        },
        lineage={
            "client_id": payload.client_id, "reporter_id": principal.subject,
            "case_id": case_id, "captured_at": _naive_utc(payload.captured_at).isoformat(),
        },
    )
    try:
        db.commit()
    except IntegrityError:
        # A service-worker retry and a foreground sync can race after the
        # initial lookup. The unique client_id is the final idempotency gate;
        # once the winning transaction commits, return that row instead of a
        # transient 500 from the losing request.
        db.rollback()
        winner = db.scalar(select(FieldObservation).where(FieldObservation.client_id == payload.client_id))
        if winner:
            if winner.organization_id != principal.organization_id:
                raise HTTPException(409, "Client identifier already belongs to another organization")
            return winner, False, _field_receipt(db, winner)
        raise
    db.refresh(row)
    db.refresh(receipt)
    return row, True, receipt


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
    payload: FieldObservationIn, background: BackgroundTasks,
    principal: Principal = Depends(require_roles("field_user", "engineer", "project_manager")),
    db: Session = Depends(get_db),
):
    row, created, receipt = _create_field_observation(payload, db, principal)
    if created:
        background.add_task(analyze_reports, [row.id])
    return {**_field_row(row), "created": created,
            "ingestion_receipt": receipt_payload(receipt) if receipt else None}


@router.post("/field/sync")
def sync_field_observations(
    payload: FieldSyncIn, background: BackgroundTasks,
    principal: Principal = Depends(require_roles("field_user", "engineer", "project_manager")),
    db: Session = Depends(get_db),
):
    results, created_ids = [], []
    for observation in payload.observations:
        row, created, receipt = _create_field_observation(observation, db, principal)
        if created:
            created_ids.append(row.id)
        results.append({"client_id": row.client_id, "id": row.id, "case_id": row.case_id,
                        "status": row.sync_status, "created": created,
                        "ingestion_receipt": receipt_payload(receipt) if receipt else None})
    if created_ids:
        # The agent organization analyses new reports after the response, so
        # a field user is never kept waiting on the model.
        background.add_task(analyze_reports, created_ids)
    return {"accepted": len(results), "results": results, "server_time": utc_now().isoformat()}


@router.get("/field/reports")
def my_field_reports(
    limit: int = Query(20, ge=1, le=100),
    principal: Principal = Depends(require_roles("viewer", "field_user", "engineer", "project_manager")),
    db: Session = Depends(get_db), lang: str = Depends(get_lang),
):
    """The current user's reports with analysis status, risk review, plan and open questions."""
    stmt = select(FieldObservation).where(
        FieldObservation.organization_id == principal.organization_id,
        FieldObservation.reporter_id == principal.subject,
    )
    if not principal.has_org_wide_project_access():
        stmt = stmt.where(FieldObservation.project_id.in_(principal.project_ids))
    rows = db.scalars(stmt.order_by(FieldObservation.captured_at.desc()).limit(limit))
    return localize([report_payload(db, row) for row in rows], lang)


@router.get("/field/observations")
def field_observations(
    project_id: int | None = None, limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(require_roles("viewer", "field_user", "engineer", "project_manager")),
    db: Session = Depends(get_db),
):
    stmt = select(FieldObservation).where(FieldObservation.organization_id == principal.organization_id)
    if project_id is not None:
        require_project(principal, project_id, db)
        stmt = stmt.where(FieldObservation.project_id == project_id)
    elif not principal.has_org_wide_project_access():
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
    require_project(principal, payload.project_id, db)
    if not db.get(Project, payload.project_id):
        raise HTTPException(404, "Project not found")
    row = TwinSource(
        id=f"TS-{uuid4().hex[:16].upper()}", organization_id=principal.organization_id,
        project_id=payload.project_id, source_type=payload.source_type, name=payload.name,
        uri=payload.uri, version=payload.version,
        coordinate_reference_system=payload.coordinate_reference_system,
        status="REGISTERED", checksum=payload.checksum, metadata_json=payload.metadata,
    )
    db.add(row)
    receipt = record_ingestion_receipt(
        db, organization_id=principal.organization_id, project_id=payload.project_id,
        channel="twin_model", source_type=payload.source_type, status="REGISTERED",
        target_type="TwinSource", target_id=row.id, checksum=payload.checksum,
        validation_summary={"schema": "valid", "crs_supplied": bool(payload.coordinate_reference_system)},
        lineage={"uri": payload.uri, "version": payload.version, "submitted_by": principal.subject},
    )
    db.commit(); db.refresh(row); db.refresh(receipt)
    return {**_twin_source_row(row), "ingestion_receipt": receipt_payload(receipt)}


@router.get("/twin/sources")
def twin_sources(
    project_id: int | None = None, principal: Principal = Depends(get_principal), db: Session = Depends(get_db),
):
    stmt = select(TwinSource).where(TwinSource.organization_id == principal.organization_id)
    if project_id is not None:
        require_project(principal, project_id, db); stmt = stmt.where(TwinSource.project_id == project_id)
    elif not principal.has_org_wide_project_access():
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
    require_project(principal, row.project_id, db)
    row.status, row.last_synced_at = "SYNCHRONIZED", utc_now()
    receipt = record_ingestion_receipt(
        db, organization_id=principal.organization_id, project_id=row.project_id,
        channel="twin_model", source_type=row.source_type, status="SYNCHRONIZED",
        target_type="TwinSource", target_id=row.id, checksum=row.checksum,
        validation_summary={"identity_preserved": True, "version_preserved": True},
        lineage={"uri": row.uri, "version": row.version, "operation": "synchronize"},
    )
    db.commit(); db.refresh(receipt)
    return {**_twin_source_row(row), "contract": "Twin ID + version + checksum preserved",
            "ingestion_receipt": receipt_payload(receipt)}


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
        "contract_version": "globalinfra.p6.activity.v1" if row.connector_type == "primavera_p6" else "globalinfra.connector.v1",
        "boundary": "Validated push/sandbox contract; no claim of a live vendor session." if row.connector_type == "primavera_p6" else "Reference connector contract",
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
        require_project(principal, payload.project_id, db)
    row = Connector(
        id=f"CON-{uuid4().hex[:16].upper()}", organization_id=principal.organization_id,
        project_id=payload.project_id, connector_type=payload.connector_type,
        name=payload.name, status="SANDBOX_CONFIGURED", config=payload.config,
    )
    db.add(row)
    receipt = record_ingestion_receipt(
        db, organization_id=principal.organization_id, project_id=payload.project_id,
        channel="enterprise_connector", source_type=payload.connector_type,
        status="CONFIGURED", target_type="Connector", target_id=row.id,
        validation_summary={"schema": "valid", "secrets_persisted": False},
        lineage={"configured_by": principal.subject, "endpoint_alias": payload.config.get("endpoint_alias")},
    )
    db.commit(); db.refresh(row); db.refresh(receipt)
    return {**_connector_row(row), "ingestion_receipt": receipt_payload(receipt)}


@router.get("/integrations/connectors")
def connectors(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.scalars(select(Connector).where(Connector.organization_id == principal.organization_id).order_by(Connector.created_at.desc()))
    return [_connector_row(row) for row in rows if row.project_id is None or principal.can_access_project(row.project_id)]


def _record_valid_for_connector(connector_type: str, record: dict) -> bool:
    if not (
        isinstance(record.get("external_id"), str)
        and isinstance(record.get("object_type"), str)
        and isinstance(record.get("updated_at"), str)
        and isinstance(record.get("payload"), dict)
    ):
        return False
    if connector_type == "primavera_p6":
        return record["object_type"].lower() in {
            "wbs", "activity", "baseline", "progress"
        }
    return True


def _sync_connector(row: Connector, payload: SyncPayload, db: Session) -> tuple[ConnectorSyncRun, IngestionReceipt]:
    rejected = sum(
        1
        for record in payload.records
        if not _record_valid_for_connector(row.connector_type, record)
    )
    accepted = len(payload.records) - rejected
    run = ConnectorSyncRun(
        id=f"SYNC-{uuid4().hex[:16].upper()}", connector_id=row.id,
        status="COMPLETED" if rejected == 0 else "COMPLETED_WITH_REJECTIONS",
        cursor=payload.cursor, records_read=len(payload.records), records_written=accepted,
        records_rejected=rejected,
        detail={"canonical_contract": ["external_id", "object_type", "updated_at", "payload"], "contract_version": "globalinfra.p6.activity.v1" if row.connector_type == "primavera_p6" else "globalinfra.connector.v1", "connection_mode": "VALIDATED_PUSH_SANDBOX", "secrets_persisted": False},
        completed_at=utc_now(),
    )
    row.status, row.last_sync_at = "SANDBOX_VALIDATED", utc_now()
    db.add(run)
    receipt = record_ingestion_receipt(
        db, organization_id=row.organization_id, project_id=row.project_id,
        channel="enterprise_connector", source_type=row.connector_type,
        status=run.status, target_type="ConnectorSyncRun", target_id=run.id,
        records_received=len(payload.records), records_accepted=accepted,
        records_rejected=rejected,
        validation_summary={
            "canonical_contract": ["external_id", "object_type", "updated_at", "payload"],
            "schema": "valid" if rejected == 0 else "partial",
        },
        lineage={"connector_id": row.id, "cursor": payload.cursor},
    )
    db.commit(); db.refresh(run); db.refresh(receipt)
    return run, receipt


def _connector_webhook_key(connector_id: str) -> bytes:
    """Derive a connector-scoped webhook key from the deployment root.

    Provision integrations with only this derived key. Compromise of one
    vendor endpoint therefore cannot authorize events for another connector.
    """
    return hmac.new(
        settings.connector_webhook_secret.encode("utf-8"),
        f"globalinfra.webhook.v1:{connector_id}".encode("utf-8"),
        hashlib.sha256,
    ).digest()


@router.post("/integrations/connectors/{connector_id}/sync")
def sync_connector(
    connector_id: str, payload: SyncPayload,
    principal: Principal = Depends(require_roles("organization_admin", "project_manager", "integration_service")),
    db: Session = Depends(get_db),
):
    row = db.get(Connector, connector_id)
    if not row or row.organization_id != principal.organization_id:
        raise HTTPException(404, "Connector not found")
    if row.project_id: require_project(principal, row.project_id, db)
    run, receipt = _sync_connector(row, payload, db)
    return {"id": run.id, "connector_id": run.connector_id, "status": run.status,
            "records_read": run.records_read, "records_written": run.records_written,
            "records_rejected": run.records_rejected, "detail": run.detail,
            "ingestion_receipt": receipt_payload(receipt)}


@router.post("/integrations/webhooks/{connector_id}")
async def connector_webhook(connector_id: str, request: Request, db: Session = Depends(get_db)):
    if not settings.connector_webhook_secret:
        raise HTTPException(503, "Connector webhook secret is not configured")
    row = db.get(Connector, connector_id)
    if row is not None:
        # Attribute accepted and rejected delivery attempts to the connector's
        # tenant without exposing connector existence before HMAC validation.
        request.state.principal = Principal(
            subject=f"webhook:{connector_id}",
            organization_id=row.organization_id,
            roles=frozenset({"integration_service"}),
            project_ids=frozenset({row.project_id}) if row.project_id else frozenset(),
            display_name=row.name,
            issuer="connector-hmac",
        )
    body = await request.body()
    supplied = request.headers.get("x-globalinfra-signature", "")
    expected = hmac.new(
        _connector_webhook_key(connector_id), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(supplied.removeprefix("sha256="), expected):
        raise HTTPException(401, "Invalid webhook signature")
    if not row: raise HTTPException(404, "Connector not found")
    try:
        import json
        data = json.loads(body)
        payload = SyncPayload.model_validate(data)
    except Exception as exc:
        raise HTTPException(422, "Invalid connector payload") from exc
    run, receipt = _sync_connector(row, payload, db)
    return {"status": run.status, "sync_run_id": run.id,
            "ingestion_receipt": receipt_payload(receipt)}


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


ROI_METRICS = {
    "first_response_minutes": "LOWER",
    "human_minutes_per_case": "LOWER",
    "evidence_completeness_percent": "HIGHER",
    "critical_miss_rate_percent": "LOWER",
    "major_rework_rate_percent": "LOWER",
    "approval_cycle_minutes": "LOWER",
    "inference_cost_per_case": "LOWER",
}


class PilotMeasurementIn(BaseModel):
    project_id: int = Field(gt=0)
    metric_name: str
    baseline_value: float = Field(ge=0)
    assisted_value: float = Field(ge=0)
    unit: str = Field(min_length=1, max_length=32)
    sample_size: int = Field(ge=1, le=1_000_000)
    evidence_ref: str = Field(min_length=3, max_length=255)
    evidence_digest: str = Field(pattern=r"^[a-fA-F0-9]{64}$")

    @field_validator("metric_name")
    @classmethod
    def supported_metric(cls, value: str) -> str:
        if value not in ROI_METRICS:
            raise ValueError("unsupported ROI metric")
        return value


class PilotVerificationIn(BaseModel):
    evidence_digest: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


def _measurement_payload(row: PilotMeasurement) -> dict:
    improvement = None
    if row.baseline_value:
        delta = (
            row.baseline_value - row.assisted_value
            if row.direction == "LOWER"
            else row.assisted_value - row.baseline_value
        )
        improvement = round(delta / row.baseline_value * 100, 2)
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "project_id": row.project_id,
        "metric_name": row.metric_name,
        "direction": row.direction,
        "baseline_value": row.baseline_value,
        "assisted_value": row.assisted_value,
        "unit": row.unit,
        "sample_size": row.sample_size,
        "improvement_percent": improvement,
        "evidence_ref": row.evidence_ref,
        "evidence_digest": row.evidence_digest,
        "status": row.status,
        "recorded_by": row.recorded_by,
        "verified_by": row.verified_by,
        "created_at": row.created_at.isoformat(),
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
    }


@router.post("/pilot/roi-measurements", status_code=201)
def create_pilot_measurement(
    payload: PilotMeasurementIn,
    principal: Principal = Depends(
        require_roles("project_manager", "organization_admin")
    ),
    db: Session = Depends(get_db),
):
    require_project(principal, payload.project_id, db)
    project = db.get(Project, payload.project_id)
    if not project or project.organization_id != principal.organization_id:
        raise HTTPException(404, "Project not found")
    row = PilotMeasurement(
        id=f"ROI-{uuid4().hex[:18].upper()}",
        organization_id=principal.organization_id,
        project_id=payload.project_id,
        metric_name=payload.metric_name,
        direction=ROI_METRICS[payload.metric_name],
        baseline_value=payload.baseline_value,
        assisted_value=payload.assisted_value,
        unit=payload.unit,
        sample_size=payload.sample_size,
        evidence_ref=payload.evidence_ref,
        evidence_digest=payload.evidence_digest.lower(),
        status="RECORDED_UNVERIFIED",
        recorded_by=principal.subject,
    )
    db.add(row)
    db.commit()
    return _measurement_payload(row)


@router.post("/pilot/roi-measurements/{measurement_id}/verify")
def verify_pilot_measurement(
    measurement_id: str,
    payload: PilotVerificationIn,
    principal: Principal = Depends(require_roles("verifier")),
    db: Session = Depends(get_db),
):
    row = db.get(PilotMeasurement, measurement_id)
    if not row or row.organization_id != principal.organization_id:
        raise HTTPException(404, "Pilot measurement not found")
    require_project(principal, row.project_id, db)
    if row.recorded_by == principal.subject:
        raise HTTPException(
            409,
            detail={
                "code": "INDEPENDENT_VERIFIER_REQUIRED",
                "message": "The recorder cannot verify the same ROI measurement.",
            },
        )
    if not hmac.compare_digest(
        payload.evidence_digest.lower(), row.evidence_digest
    ):
        raise HTTPException(
            409,
            detail={
                "code": "EVIDENCE_DIGEST_MISMATCH",
                "message": "The supplied pilot evidence does not match the recorded digest.",
            },
        )
    row.status = "VERIFIED"
    row.verified_by = principal.subject
    row.verified_at = utc_now()
    db.commit()
    return _measurement_payload(row)


@router.get("/pilot/roi-summary")
def pilot_roi_summary(
    project_id: int | None = Query(default=None, gt=0),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    stmt = select(PilotMeasurement).where(
        PilotMeasurement.organization_id == principal.organization_id
    )
    if project_id is not None:
        require_project(principal, project_id, db)
        stmt = stmt.where(PilotMeasurement.project_id == project_id)
    elif not principal.has_org_wide_project_access():
        stmt = stmt.where(PilotMeasurement.project_id.in_(principal.project_ids))
    rows = list(db.scalars(stmt.order_by(PilotMeasurement.created_at.desc())))
    verified = [row for row in rows if row.status == "VERIFIED"]
    return {
        "status": "VERIFIED_RESULTS_AVAILABLE" if verified else "NO_VERIFIED_RESULTS",
        "claimable_measurements": len(verified),
        "unverified_measurements": len(rows) - len(verified),
        "boundary": "Only independently verified measurements may be used in competition ROI claims.",
        "measurements": [_measurement_payload(row) for row in rows],
    }


def _capability_count(
    db: Session,
    model,
    principal: Principal,
    *,
    organization_column=None,
    project_column=None,
) -> int:
    """Count a capability without crossing the caller's tenant or grants.

    Some operational tables carry their organization directly, while twin
    model and telemetry rows inherit it from ``Project``.  Keeping the scope
    construction in one place makes it harder for a newly added counter to
    accidentally become a global database statistic.
    """
    stmt = select(func.count(model.id))
    if organization_column is None:
        if project_column is None:
            raise ValueError("A capability count must declare tenant ownership")
        stmt = stmt.join(Project, Project.id == project_column).where(
            Project.organization_id == principal.organization_id
        )
    else:
        stmt = stmt.where(organization_column == principal.organization_id)
    if project_column is not None and not principal.has_org_wide_project_access():
        stmt = stmt.where(project_column.in_(principal.project_ids))
    return db.scalar(stmt) or 0


@router.get("/platform/capabilities")
def platform_capabilities(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    counts = {
        "field_observations": _capability_count(
            db, FieldObservation, principal,
            organization_column=FieldObservation.organization_id,
            project_column=FieldObservation.project_id,
        ),
        "twin_sources": _capability_count(
            db, TwinSource, principal,
            organization_column=TwinSource.organization_id,
            project_column=TwinSource.project_id,
        ),
        "connectors": _capability_count(
            db, Connector, principal,
            organization_column=Connector.organization_id,
            project_column=Connector.project_id,
        ),
        # Quality runs are intentionally organization-level release evidence;
        # the schema has no project dimension to narrow further.
        "ai_quality_runs": _capability_count(
            db, AIQualityRun, principal,
            organization_column=AIQualityRun.organization_id,
        ),
        "model_versions": _capability_count(
            db, TwinModelVersion, principal,
            project_column=TwinModelVersion.project_id,
        ),
        "telemetry_readings": _capability_count(
            db, TwinTelemetryReading, principal,
            project_column=TwinTelemetryReading.project_id,
        ),
        "ingestion_receipts": _capability_count(
            db, IngestionReceipt, principal,
            organization_column=IngestionReceipt.organization_id,
            project_column=IngestionReceipt.project_id,
        ),
        "pilot_measurements": _capability_count(
            db, PilotMeasurement, principal,
            organization_column=PilotMeasurement.organization_id,
            project_column=PilotMeasurement.project_id,
        ),
    }
    return {
        "version": "6.1.0", "stage": "PHASE_10_1_UNIFIED_INGESTION",
        "release": "V6_GOVERNED_EVIDENCE_ACTION",
        "capabilities": {
            "7.1": "trusted_execution", "7.2": "oidc_rbac_multitenancy_audit",
            "7.3": "offline_field_operations", "7.4": "real_twin_source_registry",
            "7.5": "enterprise_connector_plane", "7.6": "ai_quality_release_gate",
            "7.7": "observability_security_resilience",
            "8.1": "webgl_object_level_twin", "8.2": "versioned_model_conversion",
            "8.3": "one_click_project_twin", "8.4": "realtime_iot_timeseries",
            "8.5": "4d_5d_visual_controls", "8.6": "evidence_grounded_twin_copilot",
            "8.7": "competition_showcase_mode",
            "9.1": "competition_golden_thread_and_eval_evidence",
            "10.1": "six_channel_unified_data_ingestion",
            "V6.P0": "separation_of_duties_signed_evidence_judge_sandbox",
            "V6.P1": "tenant_scoping_connector_contract_country_pack_gate",
            "V6.P2": "production_readiness_and_verified_roi_measurements",
            "V6.1": "jury_control_room_tamper_proof_immutable_release",
        },
        "counts": counts,
    }


@router.get("/platform/production-readiness")
def production_readiness():
    release_evidence = current_release_evidence()
    audit_health = audit_health_snapshot()
    verification = release_evidence.get("verification") or {}
    validation_checks = release_validation_checks(release_evidence)
    suites = release_evidence.get("suites") or []
    required_suites = {
        "AI_OUTBOUND_COMPETITION_EVIDENCE",
        "AGENT_ORGANIZATION",
        "ASSISTANT_DISPATCH",
    }
    suite_ids = {
        suite.get("id") for suite in suites if isinstance(suite, dict)
    }
    suite_results_passed = suite_ids == required_suites and all(
        suite.get("evidence_status") == "VERIFIED"
        and suite.get("reported_status") == "PASSED"
        and bool(suite.get("gates"))
        and all(value is True for value in suite["gates"].values())
        for suite in suites
        if isinstance(suite, dict)
    )
    controls = {
        "production_database": not settings.database_url.startswith("sqlite"),
        "object_storage": bool(settings.object_storage_endpoint),
        "durable_queue": bool(settings.queue_url),
        "durable_audit_outbox": settings.durable_audit_outbox_configured,
        "enterprise_identity": settings.auth_mode == "oidc",
        "separation_of_duties": settings.sod_enforced,
        "data_residency_declared": bool(settings.data_residency_region),
        "sandbox_ticket_signing": len(settings.competition_signing_secret) >= 32,
        "release_evidence_verifier_configured": (
            settings.release_evidence_verifier_configured
        ),
        "release_evidence_mounted": bool(release_evidence.get("artifact_sha256")),
        "release_evidence_authenticated": verification.get("status") == "VERIFIED",
        "release_validation_gates": all(validation_checks.values()),
        "release_suite_results": suite_results_passed,
        "audit_persistence": audit_health["status"] == "ok",
    }
    return {
        "status": "READY" if all(controls.values()) else "NOT_READY",
        "deployment_profile": settings.deployment_profile,
        "temporary_fast_launch": settings.competition_fast_launch,
        "temporary_exceptions": [
            name for name, passed in controls.items() if not passed
        ] if settings.competition_fast_launch else [],
        "controls": controls,
        "release_evidence": {
            "verification": {
                "status": verification.get("status", "UNVERIFIED"),
                "reasons": verification.get("reasons") or [],
                "scheme": verification.get("scheme"),
                "key_id": verification.get("key_id"),
                "commit": verification.get("commit"),
            },
            "validation_checks": validation_checks,
            "suite_results": {
                suite.get("id", "UNKNOWN"): {
                    "evidence_status": suite.get("evidence_status", "UNVERIFIED"),
                    "reported_status": suite.get("reported_status", "NOT_RUN"),
                    "gates": suite.get("gates") or {},
                }
                for suite in suites
                if isinstance(suite, dict)
            },
            "artifact_sha256": release_evidence.get("artifact_sha256"),
        },
        "policy": {
            "data_residency_region": settings.data_residency_region or "NOT_DECLARED",
            "backup_retention_days": settings.backup_retention_days,
            "rpo_minutes": settings.recovery_point_objective_minutes,
            "rto_minutes": settings.recovery_time_objective_minutes,
            "country_pack_review_max_age_days": settings.country_pack_review_max_age_days,
        },
        "audit": audit_health,
        "boundary": "Release readiness requires a commit-bound signed artifact, current dataset digests, four passing CI validation gates and all three passing evaluation suites. Restore drills, provider receipts and SLO measurements remain separate operational proof.",
    }
