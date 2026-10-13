"""Phase 8 operational-twin APIs: models, conversion, live data and grounded AI."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import get_db
from .i18n import bi
from .models import (Project, TwinConversionJob, TwinCopilotRun, TwinEvent,
                     TwinModelVersion, TwinObject, TwinProfile, TwinScheduleLink,
                     TwinSensor, TwinSource, TwinTelemetryReading, utc_now)
from .twin_demo import seed_synthetic_twin_sources
from .security import Principal, require_project, require_roles

router = APIRouter(prefix="/twin", tags=["phase-8-operational-twin"])


def _project(db: Session, project_id: int) -> Project:
    row = db.get(Project, project_id)
    if not row:
        raise HTTPException(404, "Project not found")
    return row


def _version(row: TwinModelVersion) -> dict:
    return {"id": row.id, "project_id": row.project_id, "version": row.version,
            "format": row.format, "status": row.status, "checksum": row.checksum,
            "uri": row.uri, "object_count": row.object_count,
            "change_summary": row.change_summary, "created_at": row.created_at.isoformat()}


@router.get("/model-versions")
def model_versions(project_id: int, db: Session = Depends(get_db)):
    _project(db, project_id)
    rows = db.scalars(select(TwinModelVersion).where(TwinModelVersion.project_id == project_id).order_by(TwinModelVersion.created_at.desc())).all()
    jobs = db.scalars(select(TwinConversionJob).where(TwinConversionJob.project_id == project_id).order_by(TwinConversionJob.started_at.desc()).limit(10)).all()
    return {"versions": [_version(row) for row in rows], "jobs": [{"id": row.id, "status": row.status, "progress": row.progress, "adapter": row.adapter, "input_format": row.input_format, "output_formats": row.output_formats, "result": row.result} for row in jobs], "external_adapters": {"ifc_converter": "NOT_CONFIGURED", "object_storage": "INTERNAL_DEMO"}}


class ConversionIn(BaseModel):
    project_id: int
    input_ref: str = Field(min_length=3, max_length=500)
    input_format: str = Field(default="IFC", max_length=24)
    output_formats: list[str] = Field(default_factory=lambda: ["GLTF", "3D_TILES"])


@router.post("/conversions", status_code=201)
def convert_model(payload: ConversionIn, principal: Principal = Depends(require_roles("engineer", "project_manager", "organization_admin")), db: Session = Depends(get_db)):
    require_project(principal, payload.project_id)
    project = _project(db, payload.project_id)
    if not set(payload.output_formats).issubset({"GLTF", "3D_TILES", "GEOJSON"}):
        raise HTTPException(422, "Unsupported output format")
    job_id = f"CONV-{uuid4().hex[:12].upper()}"
    digest = hashlib.sha256(f"{payload.input_ref}:{payload.input_format}".encode()).hexdigest()
    job = TwinConversionJob(id=job_id, project_id=project.id, input_format=payload.input_format.upper(), input_ref=payload.input_ref,
        input_checksum=digest, output_formats=payload.output_formats, status="COMPLETED", progress=100,
        adapter="synthetic-reference-adapter", result={kind: f"/backend/twin/demo-pack/{project.id}/" + ({"GLTF":"model.gltf", "3D_TILES":"tileset.json", "GEOJSON":"features.geojson"}[kind]) for kind in payload.output_formats}, completed_at=utc_now())
    version = TwinModelVersion(id=f"MV-{uuid4().hex[:12].upper()}", project_id=project.id, version=f"REV-{utc_now().strftime('%Y%m%d%H%M%S')}", format="MULTI", status="READY", checksum=digest,
        uri=f"/backend/twin/demo-pack/{project.id}/model.gltf", object_count=db.scalar(select(func.count(TwinObject.id)).where(TwinObject.project_id == project.id)) or 0,
        change_summary={"added": 0, "modified": 1, "removed": 0, "source": payload.input_ref})
    db.add_all([job, version]); db.commit()
    return {"id": job.id, "status": job.status, "progress": 100, "model_version": _version(version), "boundary": "Reference adapter executed; configure an external IFC conversion worker for customer models."}


@router.get("/model-diff")
def model_diff(project_id: int, db: Session = Depends(get_db)):
    rows = db.scalars(select(TwinModelVersion).where(TwinModelVersion.project_id == project_id).order_by(TwinModelVersion.created_at.desc()).limit(2)).all()
    if not rows:
        raise HTTPException(404, "No model versions")
    current, previous = rows[0], rows[1] if len(rows) > 1 else None
    return {"project_id": project_id, "from": previous.version if previous else None, "to": current.version,
            "changes": current.change_summary, "object_delta": current.object_count - (previous.object_count if previous else 0),
            "evidence": [current.uri, current.checksum]}


class ProjectGeneratorIn(BaseModel):
    code: str = Field(min_length=3, max_length=32, pattern=r"^[A-Z0-9-]+$")
    name: str = Field(min_length=3, max_length=120)
    country_code: str = Field(min_length=2, max_length=3)
    domain: str = Field(default="Infrastructure", max_length=80)
    kind: str = Field(default="rail", pattern=r"^(rail|metro|highway|building|energy)$")
    center: list[float] = Field(min_length=2, max_length=2)


@router.post("/projects/generate", status_code=201)
def generate_project(payload: ProjectGeneratorIn, principal: Principal = Depends(require_roles("project_manager", "organization_admin")), db: Session = Depends(get_db)):
    if db.scalar(select(Project.id).where(Project.code == payload.code)):
        raise HTTPException(409, "Project code already exists")
    project = Project(code=payload.code, name=bi(payload.name, payload.name), country_code=payload.country_code.upper(), country_name=bi(payload.country_code.upper(), payload.country_code.upper()), domain=bi(payload.domain, payload.domain), region="GLOBAL", status="ACTIVE", risk_level="MEDIUM", languages=["English", "中文"])
    db.add(project); db.flush()
    slug = payload.code.lower()
    version = utc_now().strftime("%Y.%m-A")
    db.add(TwinProfile(project_id=project.id, kind=payload.kind, slug=slug, center=payload.center, version=version))
    root = f"TWIN-{payload.code}"
    objects = [
        TwinObject(id=root, project_id=project.id, object_type="PROJECT", name=bi(payload.name, payload.name), lifecycle_stage="design", status="ACTIVE", health_score=88, progress=24, geometry_ref=f"tiles://{slug}/tileset.json", location={"lng": payload.center[0], "lat": payload.center[1]}, properties={"modelVersion": version}),
        TwinObject(id=f"{root}-ZONE01", project_id=project.id, parent_id=root, object_type="FACILITY", name=bi("Delivery Zone 01", "建设分区 01"), lifecycle_stage="construction", status="IN_PROGRESS", health_score=82, progress=41, geometry_ref=f"gltf://{slug}/model.gltf#ZONE01", location={"zone":"01"}, properties={"wbs":"1.1"}),
        TwinObject(id=f"{root}-ASSET01", project_id=project.id, parent_id=f"{root}-ZONE01", object_type="ASSET", name=bi("Primary Asset 01", "主要资产 01"), lifecycle_stage="construction", status="INSPECTION", health_score=76, progress=55, geometry_ref=f"ifc://{slug}#ASSET01", ifc_guid=hashlib.sha1(root.encode()).hexdigest()[:22], location={"zone":"01"}, properties={"wbs":"1.1.1"}),
    ]
    db.add_all(objects); db.flush()
    sensor = TwinSensor(id=f"SNS-{payload.code}-ENV", twin_id=objects[-1].id, sensor_type="ENVIRONMENT", unit="°C", status="ONLINE", threshold_warning=35, threshold_critical=42, latest_value=24.6, sampled_at=utc_now())
    db.add(sensor); db.commit()
    seed_synthetic_twin_sources(db); seed_phase8(db)
    for source in db.scalars(select(TwinSource).where(TwinSource.project_id == project.id)).all():
        source.organization_id = principal.organization_id
    db.commit()
    return {"project_id": project.id, "code": project.code, "twin_root": root, "objects": 3, "sources": 6, "model_version": version, "url": f"/twin?project_id={project.id}"}


class TelemetryIn(BaseModel):
    project_id: int
    sensor_id: str
    value: float
    sampled_at: datetime | None = None
    quality: str = "GOOD"


@router.post("/telemetry/ingest", status_code=202)
def ingest_telemetry(payload: TelemetryIn, principal: Principal = Depends(require_roles("integration_service", "engineer", "field_user")), db: Session = Depends(get_db)):
    require_project(principal, payload.project_id)
    sensor = db.get(TwinSensor, payload.sensor_id)
    if not sensor:
        raise HTTPException(404, "Sensor not found")
    obj = db.get(TwinObject, sensor.twin_id)
    if not obj or obj.project_id != payload.project_id:
        raise HTTPException(409, "Sensor is outside project scope")
    sensor.latest_value = payload.value; sensor.sampled_at = payload.sampled_at or utc_now()
    row = TwinTelemetryReading(project_id=payload.project_id, sensor_id=sensor.id, twin_id=sensor.twin_id, value=payload.value, unit=sensor.unit, quality=payload.quality, sampled_at=sensor.sampled_at)
    db.add(row); db.commit(); db.refresh(row)
    return {"reading_id": row.id, "status": "ACCEPTED", "sensor_id": sensor.id, "twin_id": sensor.twin_id}


@router.get("/telemetry/history")
def telemetry_history(project_id: int, limit: int = Query(default=60, ge=1, le=500), db: Session = Depends(get_db)):
    rows = db.scalars(select(TwinTelemetryReading).where(TwinTelemetryReading.project_id == project_id).order_by(TwinTelemetryReading.sampled_at.desc()).limit(limit)).all()
    return [{"id": row.id, "sensor_id": row.sensor_id, "twin_id": row.twin_id, "value": row.value, "unit": row.unit, "quality": row.quality, "sampled_at": row.sampled_at.isoformat()} for row in rows]


@router.get("/telemetry/live/{project_id}")
async def live_telemetry(project_id: int, events: int = Query(default=60, ge=1, le=300), db: Session = Depends(get_db)):
    ids = list(db.scalars(select(TwinObject.id).where(TwinObject.project_id == project_id)))
    sensors = list(db.scalars(select(TwinSensor).where(TwinSensor.twin_id.in_(ids)))) if ids else []
    if not sensors:
        raise HTTPException(404, "No sensors")
    async def stream():
        for index in range(events):
            now = utc_now()
            readings = [{"sensor_id": s.id, "twin_id": s.twin_id, "type": s.sensor_type, "value": round(s.latest_value + math.sin(index / 3) * max(abs(s.latest_value) * .008, .08), 2), "unit": s.unit, "status": s.status, "sampled_at": now.isoformat()} for s in sensors]
            yield f"event: telemetry\ndata: {json.dumps({'project_id': project_id, 'sequence': index + 1, 'readings': readings})}\n\n"
            await asyncio.sleep(.8)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control":"no-cache", "X-Accel-Buffering":"no"})


class CopilotIn(BaseModel):
    project_id: int
    question: str = Field(min_length=3, max_length=2000)


@router.post("/copilot/query")
def twin_copilot(payload: CopilotIn, principal: Principal = Depends(require_roles("viewer", "engineer", "project_manager")), db: Session = Depends(get_db)):
    require_project(principal, payload.project_id)
    project = _project(db, payload.project_id)
    objects = list(db.scalars(select(TwinObject).where(TwinObject.project_id == project.id).order_by(TwinObject.health_score)))
    events = list(db.scalars(select(TwinEvent).where(TwinEvent.twin_id.in_([o.id for o in objects])).order_by(TwinEvent.occurred_at.desc()))) if objects else []
    schedules = list(db.scalars(select(TwinScheduleLink).where(TwinScheduleLink.twin_id.in_([o.id for o in objects])))) if objects else []
    profile = db.get(TwinProfile, project.id)
    critical = objects[0] if objects else None
    late = min(schedules, key=lambda r: r.schedule_variance_days, default=None)
    intent = "RISK_DIAGNOSIS" if any(k in payload.question.lower() for k in ("risk", "风险", "异常")) else "PROJECT_STATUS"
    facts = []
    if critical: facts.append(f"{critical.id} health {critical.health_score:.0f}, status {critical.status}")
    if late: facts.append(f"{late.activity_id} schedule variance {late.schedule_variance_days} days")
    facts.append(f"{len(events)} active evidence-linked event(s)")
    citations = ([{"type":"TWIN_OBJECT", "ref":critical.id, "source":"twin graph", "timestamp":critical.updated_at.isoformat()}] if critical else [])
    citations += [{"type":"EVENT", "ref":event.id, "source":event.evidence_refs, "timestamp":event.occurred_at.isoformat()} for event in events[:2]]
    if profile: citations.append({"type":"MODEL_VERSION", "ref":profile.version, "source":f"/twin/demo-pack/{project.id}/manifest", "timestamp":profile.generated_at.isoformat()})
    answer = f"{project.code}: " + "; ".join(facts) + ". Review cited evidence before any project instruction or commercial action."
    run = TwinCopilotRun(id=f"TC-{uuid4().hex[:14].upper()}", project_id=project.id, query=payload.question, intent=intent, answer=answer, citations=citations, confidence=.91 if citations else .55)
    db.add(run); db.commit()
    return {"run_id": run.id, "intent": intent, "answer": answer, "citations": citations, "confidence": run.confidence, "grounded": bool(citations), "requires_approval": True, "model_route": "deterministic-grounded-twin"}


@router.get("/showcase/{project_id}")
def showcase(project_id: int, db: Session = Depends(get_db)):
    project = _project(db, project_id)
    return {"project": {"id":project.id, "code":project.code, "name":project.name}, "duration_seconds":180, "steps":[
        {"id":"8.1", "title":"Real 3D", "seconds":28, "action":"Inspect GLTF object and its stable Twin ID"},
        {"id":"8.2", "title":"Model pipeline", "seconds":22, "action":"Compare traceable model versions"},
        {"id":"8.3", "title":"One-click twin", "seconds":20, "action":"Generate a six-format project pack"},
        {"id":"8.4", "title":"Live IoT", "seconds":24, "action":"Stream sensor values over SSE"},
        {"id":"8.5", "title":"4D / 5D", "seconds":30, "action":"Scrub progress and color schedule/cost exposure"},
        {"id":"8.6", "title":"Grounded Copilot", "seconds":34, "action":"Ask a risk question and inspect citations"},
        {"id":"8.7", "title":"Decision close", "seconds":22, "action":"Show evidence and approval boundary"},
    ]}


def seed_phase8(db: Session) -> None:
    configs = {1:("rail", "my-rail-a", [101.687, 3.139], "2026.10-A"), 2:("highway", "id-highway-b", [106.8456, -6.2088], "2026.10-B"), 3:("metro", "sa-metro-c", [46.6753, 24.7136], "2026.10-C")}
    for project_id, (kind, slug, center, version) in configs.items():
        if db.get(Project, project_id) and not db.get(TwinProfile, project_id):
            db.add(TwinProfile(project_id=project_id, kind=kind, slug=slug, center=center, version=version))
    db.flush()
    for profile in db.scalars(select(TwinProfile)).all():
        count = db.scalar(select(func.count(TwinObject.id)).where(TwinObject.project_id == profile.project_id)) or 0
        for suffix, delta in (("BASE", -1), ("CURRENT", 0)):
            row_id = f"MV-{profile.project_id}-{suffix}"
            if not db.get(TwinModelVersion, row_id):
                db.add(TwinModelVersion(id=row_id, project_id=profile.project_id, version=profile.version + ("-BASE" if delta else ""), format="GLTF", status="READY", checksum=hashlib.sha256(row_id.encode()).hexdigest(), uri=f"/backend/twin/demo-pack/{profile.project_id}/model.gltf", object_count=max(0, count + delta), change_summary={"added": max(delta + 1, 0), "modified": 2 if not delta else 0, "removed": 0}))
    db.flush()
    for sensor in db.scalars(select(TwinSensor)).all():
        obj = db.get(TwinObject, sensor.twin_id)
        if obj and db.scalar(select(func.count(TwinTelemetryReading.id)).where(TwinTelemetryReading.sensor_id == sensor.id)) == 0:
            for offset in range(12, 0, -1):
                db.add(TwinTelemetryReading(project_id=obj.project_id, sensor_id=sensor.id, twin_id=sensor.twin_id, value=round(sensor.latest_value * (1 + math.sin(offset) * .012), 2), unit=sensor.unit, quality="GOOD", sampled_at=utc_now()-timedelta(minutes=offset*5)))
    db.commit()
