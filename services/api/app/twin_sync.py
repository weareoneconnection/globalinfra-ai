"""Write-back from governed work orders and telemetry into the digital twin.

The twin is not a read-only picture: when a work order linked to a twin object
is opened, independently verified or closed, the object's event moves through
the same states and its timeline records the signed receipt that caused the
change. Telemetry that crosses a threshold opens a twin event and a maintenance
record that waits for human approval.

Paperwork never changes an asset's physical status: a verified reply letter
does not mean a crack is repaired. Write-back therefore updates the linked twin
event and appends evidence to the object's state history while keeping the
object's own status unchanged.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .i18n import bi
from .models import (
    Case, FieldObservation, MaintenanceRecord, TwinEvent, TwinObject,
    TwinSensor, TwinStateHistory, utc_now,
)

log = logging.getLogger(__name__)

# Element references used in notices and letters, e.g. "Pier P47", "ST04", "AHU01".
ELEMENT_RE = re.compile(r"\b([PS]\d{1,3}|ST\d{2}|BRG\d{1,3}[A-Z]?|AHU\d{2})\b", re.IGNORECASE)

WORK_ORDER_SOURCE = "GOVERNED_WORK_ORDER"
TELEMETRY_SOURCE = "IOT_THRESHOLD"
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def _text(value) -> str:
    if isinstance(value, dict):
        return " ".join(str(item) for item in value.values() if item)
    return str(value or "")


def case_twin_ids(db: Session, case: Case) -> list[str]:
    """Twin objects a work order refers to: explicit field links first, then element tokens."""
    if case is None or case.project_id is None:
        return []
    ids = {
        twin_id for twin_id in db.scalars(
            select(FieldObservation.twin_id).where(FieldObservation.case_id == case.id)
        ) if twin_id
    }
    tokens = {match.upper() for match in ELEMENT_RE.findall(f"{_text(case.title)} {_text(case.description)}")}
    if tokens:
        for obj_id in db.scalars(select(TwinObject.id).where(TwinObject.project_id == case.project_id)):
            if any(obj_id.upper().endswith(f"-{token}") for token in tokens):
                ids.add(obj_id)
    valid = set(db.scalars(select(TwinObject.id).where(
        TwinObject.id.in_(ids), TwinObject.project_id == case.project_id,
    ))) if ids else set()
    return sorted(valid)


def _event_id(case_id: str, twin_id: str) -> str:
    return "EVT-WO-" + hashlib.sha256(f"{case_id}|{twin_id}".encode()).hexdigest()[:16].upper()


def sync_case_to_twin(db: Session, case: Case, stage: str, evidence_ref: str | None = None) -> list[str]:
    """Move the twin events linked to ``case`` to ``stage`` and log the receipt.

    Never raises: a twin write-back failure must not block the governed
    workflow that called it. Changes are added to the caller's session and
    committed with the caller's transaction.
    """
    try:
        twin_ids = case_twin_ids(db, case)
        now = utc_now()
        severity = str(case.risk or "MEDIUM").upper()
        severity = severity if severity in SEVERITIES else "MEDIUM"
        for twin_id in twin_ids:
            obj = db.get(TwinObject, twin_id)
            event_id = _event_id(case.id, twin_id)
            event = db.get(TwinEvent, event_id)
            if event is None:
                event = TwinEvent(
                    id=event_id, twin_id=twin_id, event_type="WORK_ORDER", severity=severity,
                    title=case.title if isinstance(case.title, dict) else bi(str(case.title), str(case.title)),
                    domain="governed_execution", status=stage, evidence_refs=[case.id],
                    occurred_at=case.created_at or now,
                )
                db.add(event)
            event.status = stage
            refs = list(event.evidence_refs or [])
            if evidence_ref and evidence_ref not in refs:
                refs.append(evidence_ref)
            event.evidence_refs = refs
            db.add(TwinStateHistory(
                twin_id=twin_id, previous_status=obj.status, status=obj.status,
                source_system=f"{WORK_ORDER_SOURCE}:{stage}"[:64],
                evidence_ref=(evidence_ref or case.id)[:255], confidence=1.0, effective_at=now,
            ))
            obj.updated_at = now
        return twin_ids
    except Exception:  # pragma: no cover - defensive; workflow must continue
        log.exception("twin write-back failed for case %s", getattr(case, "id", None))
        return []


def sensor_level(sensor: TwinSensor, value: float) -> str:
    if value >= sensor.threshold_critical:
        return "CRITICAL"
    if value >= sensor.threshold_warning:
        return "WARNING"
    return "NORMAL"


def raise_threshold_alert(db: Session, sensor: TwinSensor, value: float, reading_ref: str) -> dict | None:
    """Open (or escalate) one twin event and one approval-gated maintenance record per sensor."""
    level = sensor_level(sensor, value)
    if level == "NORMAL":
        return None
    severity = "HIGH" if level == "CRITICAL" else "MEDIUM"
    open_events = [
        row for row in db.scalars(select(TwinEvent).where(
            TwinEvent.twin_id == sensor.twin_id, TwinEvent.event_type == "THRESHOLD",
            TwinEvent.status == "OPEN",
        )) if sensor.id in (row.evidence_refs or [])
    ]
    now = utc_now()
    if open_events:
        event = open_events[0]
        if severity == "HIGH":
            event.severity = "HIGH"
        event.evidence_refs = [*event.evidence_refs, reading_ref][-20:]
        created = False
    else:
        limit = sensor.threshold_critical if level == "CRITICAL" else sensor.threshold_warning
        event = TwinEvent(
            id=f"EVT-TLM-{uuid4().hex[:12].upper()}", twin_id=sensor.twin_id, event_type="THRESHOLD",
            severity=severity,
            title=bi(f"{sensor.sensor_type} {value} {sensor.unit} reached {level.lower()} threshold {limit}",
                     f"{sensor.sensor_type} 读数 {value} {sensor.unit} 达到{'严重' if level == 'CRITICAL' else '预警'}阈值 {limit}"),
            domain="operations", status="OPEN", evidence_refs=[sensor.id, reading_ref], occurred_at=now,
        )
        db.add(event)
        created = True
    maintenance_id = f"WO-TLM-{event.id[-12:]}"
    maintenance = db.get(MaintenanceRecord, maintenance_id)
    if maintenance is None:
        maintenance = MaintenanceRecord(
            id=maintenance_id, twin_id=sensor.twin_id, work_type="CONDITION_BASED",
            status="AWAITING_APPROVAL", priority="HIGH" if level == "CRITICAL" else "MEDIUM",
            description=bi(f"Inspect {sensor.sensor_type.lower()} condition flagged by {sensor.id}",
                           f"检查 {sensor.id} 报出的 {sensor.sensor_type} 异常"),
            due_at=now + timedelta(days=1 if level == "CRITICAL" else 3),
        )
        db.add(maintenance)
    elif level == "CRITICAL":
        maintenance.priority = "HIGH"
    db.add(TwinStateHistory(
        twin_id=sensor.twin_id, previous_status=db.get(TwinObject, sensor.twin_id).status,
        status=db.get(TwinObject, sensor.twin_id).status,
        source_system=f"{TELEMETRY_SOURCE}:{level}", evidence_ref=reading_ref[:255],
        confidence=1.0, effective_at=now,
    ))
    return {"level": level, "event_id": event.id, "event_created": created,
            "maintenance_id": maintenance.id, "maintenance_status": maintenance.status}
