"""Unified six-channel data-ingestion control plane.

Domain records remain domain records.  This module provides a consistent
catalog, validation receipt and lineage envelope across each entry channel;
it does not flatten every input into a generic event.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import get_db
from .i18n import bi, get_lang, localize
from .models import IngestionReceipt, Project
from .security import Principal, get_principal, require_project, require_roles


router = APIRouter(prefix="/ingestion", tags=["unified-data-ingestion"])

CHANNELS = (
    "event_work_order",
    "document_correspondence",
    "project_master",
    "enterprise_connector",
    "twin_model",
    "iot_telemetry",
)

CHANNEL_CATALOG = [
    {
        "id": "event_work_order", "code": "01", "icon": "WO",
        "name": bi("Events & work orders", "事件与工单"),
        "description": bi("Field observations, inspections, NCRs, RFIs and actionable notices.", "现场观察、检查、NCR、RFI 与可执行通知。"),
        "source_types": ["mobile_field", "text", "inspection", "ncr", "rfi"],
        "canonical_objects": ["FieldObservation", "Case"],
        "endpoint": "/field/observations · /intake/text",
        "event_policy": bi("Actionable records create workflow events or cases.", "仅可执行记录触发工作流事件或工单。"),
    },
    {
        "id": "document_correspondence", "code": "02", "icon": "DOC",
        "name": bi("Documents & correspondence", "文档与函件"),
        "description": bi("Contracts, drawings, specifications, letters and transmittals with version lineage.", "合同、图纸、规范、函件与传递单，保留版本血缘。"),
        "source_types": ["PDF", "DOCX", "TXT", "letter", "transmittal"],
        "canonical_objects": ["SourceDocument", "IntakeSubmission", "KnowledgeDocument"],
        "endpoint": "/intake/document",
        "event_policy": bi("Documents remain documents; extracted obligations may create cases.", "文档保持为文档；抽取出的义务可生成工单。"),
    },
    {
        "id": "project_master", "code": "03", "icon": "MDM",
        "name": bi("Project master data", "项目主数据"),
        "description": bi("Project identity, country, domain, region, languages and governance baseline.", "项目身份、国家、领域、区域、语言与治理基线。"),
        "source_types": ["manual", "portfolio_import", "project_factory"],
        "canonical_objects": ["Project"],
        "endpoint": "/ingestion/project-master",
        "event_policy": bi("Master-data changes emit events only after validation and approval.", "主数据变更仅在校验和审批后触发事件。"),
    },
    {
        "id": "enterprise_connector", "code": "04", "icon": "ERP",
        "name": bi("Enterprise system connectors", "企业系统连接器"),
        "description": bi("P6, ACC, SharePoint, SAP/Oracle, ArcGIS and MQTT adapters.", "P6、ACC、SharePoint、SAP/Oracle、ArcGIS 与 MQTT 适配器。"),
        "source_types": ["primavera_p6", "autodesk_acc", "sharepoint", "sap", "arcgis", "mqtt"],
        "canonical_objects": ["Connector", "ConnectorSyncRun"],
        "endpoint": "/integrations/connectors",
        "event_policy": bi("Mapped deltas may emit domain events; sync records remain integration evidence.", "映射后的差异可触发领域事件；同步记录保留为集成证据。"),
    },
    {
        "id": "twin_model", "code": "05", "icon": "BIM",
        "name": bi("BIM / GIS / digital-twin models", "BIM/GIS/数字孪生模型"),
        "description": bi("IFC, GLTF, 3D Tiles, GeoJSON, WMS and model-version sources.", "IFC、GLTF、3D Tiles、GeoJSON、WMS 与模型版本数据源。"),
        "source_types": ["IFC", "GLTF", "3D_TILES", "GEOJSON", "WMS"],
        "canonical_objects": ["TwinSource", "TwinModelVersion", "TwinObject"],
        "endpoint": "/twin/sources",
        "event_policy": bi("Model revisions produce change sets; only material changes emit alerts.", "模型版本先生成差异集；仅重大变化触发告警。"),
    },
    {
        "id": "iot_telemetry", "code": "06", "icon": "IoT",
        "name": bi("IoT / telemetry data", "IoT/遥测数据"),
        "description": bi("Time-series readings from sensors, BMS, SCADA and edge gateways.", "来自传感器、BMS、SCADA 与边缘网关的时序读数。"),
        "source_types": ["sensor", "bms", "scada", "mqtt"],
        "canonical_objects": ["TwinTelemetryReading", "TwinSensor"],
        "endpoint": "/twin/telemetry/ingest",
        "event_policy": bi("Readings remain time series; threshold breaches emit events.", "读数保持为时序数据；仅阈值越界触发事件。"),
    },
]


def receipt_payload(row: IngestionReceipt) -> dict:
    return {
        "id": row.id, "organization_id": row.organization_id,
        "project_id": row.project_id, "channel": row.channel,
        "source_type": row.source_type, "status": row.status,
        "records_received": row.records_received,
        "records_accepted": row.records_accepted,
        "records_rejected": row.records_rejected,
        "target_type": row.target_type, "target_id": row.target_id,
        "checksum": row.checksum, "mapping_version": row.mapping_version,
        "validation_summary": row.validation_summary, "lineage": row.lineage,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def record_ingestion_receipt(
    db: Session, *, organization_id: str, channel: str, source_type: str,
    status: str, target_type: str, project_id: int | None = None,
    target_id: str | int | None = None, records_received: int = 1,
    records_accepted: int = 1, records_rejected: int = 0,
    checksum: str | None = None, validation_summary: dict | None = None,
    lineage: dict | None = None,
) -> IngestionReceipt:
    if channel not in CHANNELS:
        raise ValueError(f"Unsupported ingestion channel: {channel}")
    row = IngestionReceipt(
        id=f"ING-{uuid4().hex[:20].upper()}", organization_id=organization_id,
        project_id=project_id, channel=channel, source_type=source_type,
        status=status, records_received=records_received,
        records_accepted=records_accepted, records_rejected=records_rejected,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        checksum=checksum, validation_summary=validation_summary or {},
        lineage=lineage or {},
    )
    db.add(row)
    return row


def _scoped_receipts(principal: Principal):
    stmt = select(IngestionReceipt).where(IngestionReceipt.organization_id == principal.organization_id)
    if principal.project_ids:
        stmt = stmt.where(
            (IngestionReceipt.project_id.is_(None)) |
            (IngestionReceipt.project_id.in_(principal.project_ids))
        )
    return stmt


@router.get("/catalog")
def ingestion_catalog(lang: str = Depends(get_lang)):
    return {
        "version": "globalinfra.canonical.v1", "channel_count": len(CHANNELS),
        "principle": localize(bi(
            "Data stays in its domain object; events are emitted only for actionable changes.",
            "数据保留在各自领域对象中；只有可执行变化才触发事件。",
        ), lang),
        "channels": localize(CHANNEL_CATALOG, lang),
    }


@router.get("/receipts")
def ingestion_receipts(
    channel: str | None = Query(default=None),
    project_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=30, ge=1, le=200),
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db),
):
    if channel is not None and channel not in CHANNELS:
        raise HTTPException(422, "Unsupported ingestion channel")
    if project_id is not None:
        require_project(principal, project_id)
    stmt = _scoped_receipts(principal)
    if channel:
        stmt = stmt.where(IngestionReceipt.channel == channel)
    if project_id:
        stmt = stmt.where(IngestionReceipt.project_id == project_id)
    rows = db.scalars(stmt.order_by(IngestionReceipt.created_at.desc()).limit(limit)).all()
    return [receipt_payload(row) for row in rows]


@router.get("/summary")
def ingestion_summary(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db),
):
    scoped = _scoped_receipts(principal).subquery()
    channel_rows = db.execute(
        select(scoped.c.channel, func.count(scoped.c.id),
               func.coalesce(func.sum(scoped.c.records_accepted), 0),
               func.coalesce(func.sum(scoped.c.records_rejected), 0))
        .group_by(scoped.c.channel)
    ).all()
    status_rows = db.execute(
        select(scoped.c.status, func.count(scoped.c.id)).group_by(scoped.c.status)
    ).all()
    recent = db.scalars(
        _scoped_receipts(principal).order_by(IngestionReceipt.created_at.desc()).limit(12)
    ).all()
    by_channel = {channel: {"operations": 0, "accepted": 0, "rejected": 0} for channel in CHANNELS}
    for channel, operations, accepted, rejected in channel_rows:
        by_channel[channel] = {"operations": operations, "accepted": accepted, "rejected": rejected}
    return {
        "channel_count": len(CHANNELS),
        "active_channels": sum(1 for value in by_channel.values() if value["operations"]),
        "operations": sum(value["operations"] for value in by_channel.values()),
        "records_accepted": sum(value["accepted"] for value in by_channel.values()),
        "records_rejected": sum(value["rejected"] for value in by_channel.values()),
        "by_channel": by_channel,
        "by_status": {status: count for status, count in status_rows},
        "recent": [receipt_payload(row) for row in recent],
    }


class ProjectMasterIn(BaseModel):
    code: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    name: str = Field(min_length=3, max_length=160)
    country_code: str = Field(min_length=2, max_length=3)
    country_name: str | None = Field(default=None, max_length=120)
    domain: str = Field(min_length=2, max_length=120)
    region: str = Field(default="GLOBAL", min_length=2, max_length=80)
    languages: list[str] = Field(default_factory=lambda: ["English"], min_length=1, max_length=12)
    risk_level: str = "MEDIUM"

    @field_validator("risk_level")
    @classmethod
    def valid_risk(cls, value: str) -> str:
        value = value.upper()
        if value not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            raise ValueError("unsupported risk level")
        return value


@router.post("/project-master", status_code=201)
def ingest_project_master(
    payload: ProjectMasterIn,
    principal: Principal = Depends(require_roles("project_manager", "organization_admin")),
    db: Session = Depends(get_db), lang: str = Depends(get_lang),
):
    code = payload.code.upper()
    if db.scalar(select(Project.id).where(Project.code == code)):
        raise HTTPException(409, "Project code already exists")
    country_code = payload.country_code.upper()
    row = Project(
        code=code, name=bi(payload.name), country_code=country_code,
        country_name=bi(payload.country_name or country_code), domain=bi(payload.domain),
        region=payload.region.upper(), status="ACTIVE", risk_level=payload.risk_level,
        languages=payload.languages,
    )
    db.add(row)
    db.flush()
    receipt = record_ingestion_receipt(
        db, organization_id=principal.organization_id, project_id=row.id,
        channel="project_master", source_type="manual", status="ACCEPTED",
        target_type="Project", target_id=row.id,
        validation_summary={"schema": "valid", "duplicate_code": False, "risk_level": payload.risk_level},
        lineage={"submitted_by": principal.subject, "source": "data_ingestion_center"},
    )
    db.commit()
    db.refresh(row)
    db.refresh(receipt)
    return localize({
        "project": {"id": row.id, "code": row.code, "name": row.name,
                    "country_code": row.country_code, "country_name": row.country_name,
                    "domain": row.domain, "region": row.region,
                    "status": row.status, "risk_level": row.risk_level,
                    "languages": row.languages},
        "ingestion_receipt": receipt_payload(receipt),
    }, lang)


def seed_ingestion_receipts(db: Session) -> None:
    """Seed explicit synthetic receipts so the demo never implies live data."""
    examples = [
        ("DEMO-EVENT", "event_work_order", "mobile_field", "FieldObservation", "FO-DEMO-001"),
        ("DEMO-DOC", "document_correspondence", "PDF", "SourceDocument", "DOC-DEMO-001"),
        ("DEMO-MASTER", "project_master", "portfolio_fixture", "Project", "1"),
        ("DEMO-CONNECTOR", "enterprise_connector", "primavera_p6", "Connector", "CON-DEMO-P6"),
        ("DEMO-TWIN", "twin_model", "IFC", "TwinSource", "TS-MYRAIL-IFC"),
        ("DEMO-IOT", "iot_telemetry", "sensor", "TwinTelemetryReading", "TELEM-DEMO-001"),
    ]
    for suffix, channel, source_type, target_type, target_id in examples:
        receipt_id = f"ING-{suffix}"
        if db.get(IngestionReceipt, receipt_id):
            continue
        db.add(IngestionReceipt(
            id=receipt_id, organization_id="globalinfra-demo", project_id=1,
            channel=channel, source_type=source_type, status="SYNTHETIC_DEMO",
            records_received=1, records_accepted=1, records_rejected=0,
            target_type=target_type, target_id=target_id,
            mapping_version="globalinfra.canonical.v1",
            validation_summary={"schema": "valid", "data_boundary": "synthetic"},
            lineage={"provenance": "SYNTHETIC_DEMO", "source": "seed_fixture"},
        ))
    db.commit()
