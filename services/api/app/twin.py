"""V2.1 full-lifecycle digital twin API.

The module keeps geometry references, engineering identity, 4D/5D controls,
commissioning, telemetry and Governed Scenario Analysis behind one
project-scoped contract. Seed data is explicitly synthetic fixture data;
adapters can replace it without changing the UI or Twin ID model.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import get_db
from .i18n import bi, get_lang, localize
from .models import (
    CommissioningItem, MaintenanceRecord, TwinEvent, TwinObject, TwinRelation,
    TwinScenario, TwinScheduleLink, TwinSensor, TwinStateHistory, utc_now,
)

router = APIRouter(prefix="/twin", tags=["digital-twin"])

TWIN_AGENTS = [
    {"id": "twin-orchestrator", "name": bi("Twin Orchestrator", "孪生编排智能体"), "scope": bi("Routes spatial, temporal and domain reasoning", "编排空间、时间与专业推理")},
    {"id": "bim-gis", "name": bi("BIM / GIS Agent", "BIM / GIS 智能体"), "scope": bi("Geometry, location and model-version context", "几何、位置与模型版本上下文")},
    {"id": "progress-twin", "name": bi("4D / 5D Controls Agent", "4D / 5D 项控智能体"), "scope": bi("Schedule, quantity and cost impact", "进度、工程量与成本影响")},
    {"id": "interface-twin", "name": bi("Interface Agent", "接口智能体"), "scope": bi("Physical and contractual interface conflicts", "物理与合同接口冲突")},
    {"id": "commissioning-twin", "name": bi("Commissioning Agent", "调试智能体"), "scope": bi("Test packs, punch and handover readiness", "试验包、遗留项与移交准备度")},
    {"id": "asset-health", "name": bi("Asset Health Agent", "资产健康智能体"), "scope": bi("Telemetry anomaly and maintenance prognosis", "遥测异常与维修预测")},
    {"id": "twin-verifier", "name": bi("Twin Verification Agent", "孪生核验智能体"), "scope": bi("Evidence, time and model-version validation", "证据、时间与模型版本核验")},
]


def _object(row: TwinObject) -> dict:
    return {"id": row.id, "project_id": row.project_id, "parent_id": row.parent_id,
            "object_type": row.object_type, "name": row.name, "lifecycle_stage": row.lifecycle_stage,
            "status": row.status, "health_score": row.health_score, "progress": row.progress,
            "geometry_ref": row.geometry_ref, "ifc_guid": row.ifc_guid, "location": row.location,
            "properties": row.properties, "updated_at": row.updated_at.isoformat()}


@router.get("/summary")
def summary(project_id: int | None = Query(default=None), db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    condition = TwinObject.project_id == project_id if project_id else True
    objects = list(db.scalars(select(TwinObject).where(condition)))
    ids = [obj.id for obj in objects]
    events = list(db.scalars(select(TwinEvent).where(TwinEvent.twin_id.in_(ids)))) if ids else []
    sensors = list(db.scalars(select(TwinSensor).where(TwinSensor.twin_id.in_(ids)))) if ids else []
    schedule = list(db.scalars(select(TwinScheduleLink).where(TwinScheduleLink.twin_id.in_(ids)))) if ids else []
    commissioning = list(db.scalars(select(CommissioningItem).where(CommissioningItem.twin_id.in_(ids)))) if ids else []
    payload = {
        "maturity": "PHASE_6", "sync_status": "SYNCHRONIZED", "model_version": "IFC-REV-C / GIS-2026.10",
        "data_provenance": "SYNTHETIC_FIXTURE_DATA",
        "is_synthetic_fixture": True,
        "objects": len(objects), "mapped_objects": len([o for o in objects if o.geometry_ref]),
        "average_health": round(sum(o.health_score for o in objects) / len(objects), 1) if objects else 0,
        "active_events": len([e for e in events if e.status not in {"CLOSED", "RESOLVED"}]),
        "critical_events": len([e for e in events if e.severity in {"HIGH", "CRITICAL"}]),
        "online_sensors": len([s for s in sensors if s.status == "ONLINE"]),
        "schedule_variance_days": min([s.schedule_variance_days for s in schedule], default=0),
        "cost_exposure_m": round(sum(max(0, s.forecast - s.budget) for s in schedule), 2),
        "commissioning_readiness": round(sum(c.readiness for c in commissioning) / len(commissioning), 1) if commissioning else 0,
        "handover_completeness": round(sum(c.document_completeness for c in commissioning) / len(commissioning), 1) if commissioning else 0,
        "layers": [
            bi("Spatial / BIM / GIS", "空间 / BIM / GIS"), bi("Asset graph", "资产图谱"),
            bi("4D schedule", "4D 进度"), bi("5D cost", "5D 成本"), bi("Quality & HSE", "质量与 HSE"),
            bi("Commissioning", "调试移交"), bi("Operations / IoT", "运营 / IoT"), bi("Governed Scenario Analysis", "受管控场景分析"),
        ],
    }
    return localize(payload, lang)


@router.get("/scene")
def scene(project_id: int = Query(default=1), db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    objects = list(db.scalars(select(TwinObject).where(TwinObject.project_id == project_id).order_by(TwinObject.id)))
    ids = [obj.id for obj in objects]
    events = list(db.scalars(select(TwinEvent).where(TwinEvent.twin_id.in_(ids)).order_by(TwinEvent.occurred_at.desc()))) if ids else []
    payload = {
        "project_id": project_id,
        "data_provenance": "SYNTHETIC_FIXTURE_DATA",
        "is_synthetic_fixture": True,
        "coordinate_system": "EPSG:4326 + Project Chainage",
        "geometry_protocols": ["IFC 4.3", "glTF 2.0", "3D Tiles 1.1", "GeoJSON"],
        "objects": [_object(obj) for obj in objects],
        "events": [{"id": e.id, "twin_id": e.twin_id, "event_type": e.event_type, "severity": e.severity,
                    "title": e.title, "domain": e.domain, "status": e.status, "evidence_refs": e.evidence_refs,
                    "occurred_at": e.occurred_at.isoformat()} for e in events],
    }
    return localize(payload, lang)


@router.get("/objects/{twin_id}")
def object_detail(twin_id: str, db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    obj = db.get(TwinObject, twin_id)
    if not obj:
        raise HTTPException(404, "Twin object not found")
    relations = list(db.scalars(select(TwinRelation).where((TwinRelation.source_id == twin_id) | (TwinRelation.target_id == twin_id))))
    states = list(db.scalars(select(TwinStateHistory).where(TwinStateHistory.twin_id == twin_id).order_by(TwinStateHistory.effective_at.desc())))
    events = list(db.scalars(select(TwinEvent).where(TwinEvent.twin_id == twin_id).order_by(TwinEvent.occurred_at.desc())))
    sensors = list(db.scalars(select(TwinSensor).where(TwinSensor.twin_id == twin_id)))
    payload = {**_object(obj),
        "relations": [{"source_id": r.source_id, "target_id": r.target_id, "type": r.relation_type, "metadata": r.metadata_json} for r in relations],
        "state_history": [{"previous_status": s.previous_status, "status": s.status, "source_system": s.source_system,
                           "evidence_ref": s.evidence_ref, "confidence": s.confidence, "effective_at": s.effective_at.isoformat()} for s in states],
        "events": [{"id": e.id, "type": e.event_type, "severity": e.severity, "title": e.title, "status": e.status, "evidence_refs": e.evidence_refs} for e in events],
        "sensors": [{"id": s.id, "type": s.sensor_type, "unit": s.unit, "status": s.status, "value": s.latest_value,
                     "warning": s.threshold_warning, "critical": s.threshold_critical, "sampled_at": s.sampled_at.isoformat()} for s in sensors],
    }
    return localize(payload, lang)


@router.get("/controls")
def controls(project_id: int = Query(default=1), db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    rows = db.execute(select(TwinScheduleLink, TwinObject).join(TwinObject, TwinScheduleLink.twin_id == TwinObject.id).where(TwinObject.project_id == project_id)).all()
    payload = [{"twin_id": obj.id, "name": obj.name, "wbs_code": link.wbs_code, "activity_id": link.activity_id,
                "planned_progress": link.planned_progress, "actual_progress": link.actual_progress,
                "variance": link.actual_progress-link.planned_progress, "schedule_variance_days": link.schedule_variance_days,
                "cost_code": link.cost_code, "budget_m": link.budget, "forecast_m": link.forecast,
                "cost_variance_m": round(link.forecast-link.budget, 2)} for link, obj in rows]
    return localize(payload, lang)


@router.get("/commissioning")
def commissioning(project_id: int = Query(default=1), db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    rows = db.execute(select(CommissioningItem, TwinObject).join(TwinObject, CommissioningItem.twin_id == TwinObject.id).where(TwinObject.project_id == project_id)).all()
    payload = [{"id": item.id, "twin_id": obj.id, "asset": obj.name, "system": item.system, "test_pack": item.test_pack,
                "stage": item.stage, "punch_open": item.punch_open, "document_completeness": item.document_completeness,
                "readiness": item.readiness} for item, obj in rows]
    return localize(payload, lang)


@router.get("/operations")
def operations(project_id: int = Query(default=1), db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    assets = {o.id: o for o in db.scalars(select(TwinObject).where(TwinObject.project_id == project_id))}
    ids = list(assets)
    sensors = list(db.scalars(select(TwinSensor).where(TwinSensor.twin_id.in_(ids)))) if ids else []
    work = list(db.scalars(select(MaintenanceRecord).where(MaintenanceRecord.twin_id.in_(ids)).order_by(MaintenanceRecord.due_at))) if ids else []
    payload = {
        "sensors": [{"id": s.id, "twin_id": s.twin_id, "asset": assets[s.twin_id].name, "type": s.sensor_type,
                     "unit": s.unit, "value": s.latest_value, "status": "WARNING" if s.latest_value >= s.threshold_warning else "NORMAL",
                     "warning": s.threshold_warning, "critical": s.threshold_critical, "sampled_at": s.sampled_at.isoformat()} for s in sensors],
        "maintenance": [{"id": m.id, "twin_id": m.twin_id, "asset": assets[m.twin_id].name, "work_type": m.work_type,
                         "status": m.status, "priority": m.priority, "description": m.description, "due_at": m.due_at.isoformat()} for m in work],
    }
    return localize(payload, lang)


@router.get("/scenarios")
def scenarios(project_id: int = Query(default=1), db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    rows = list(db.scalars(select(TwinScenario).where(TwinScenario.project_id == project_id).order_by(TwinScenario.id)))
    return localize([{"id": s.id, "name": s.name, "type": s.scenario_type, "status": s.status,
                      "assumptions": s.assumptions, "result": s.result, "requires_approval": s.requires_approval,
                      "updated_at": s.updated_at.isoformat()} for s in rows], lang)


class ScenarioRunRequest(BaseModel):
    adjustment_percent: float = Field(default=0, ge=-25, le=25)


@router.post("/scenarios/{scenario_id}/run")
def run_scenario(scenario_id: str, payload: ScenarioRunRequest, db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    scenario = db.get(TwinScenario, scenario_id)
    if not scenario:
        raise HTTPException(404, "Twin scenario not found")
    factor = 1 + payload.adjustment_percent / 100
    result = dict(scenario.result)
    for key, value in list(result.items()):
        if isinstance(value, (int, float)) and key != "confidence":
            result[key] = round(value * factor, 2)
    result["confidence"] = scenario.result.get("confidence", .8)
    result["execution_status"] = "AWAITING_APPROVAL" if scenario.requires_approval else "ADVISORY_ONLY"
    result["evidence"] = ["Twin object state", "4D/5D baseline", "Latest telemetry", "Scenario assumptions"]
    scenario.result = result
    scenario.status = "ANALYZED"
    scenario.updated_at = utc_now()
    db.commit()
    return localize({"scenario_id": scenario.id, "result": result,
                     "analysis_type": "Governed Scenario Analysis",
                     "data_provenance": "SYNTHETIC_FIXTURE_DATA",
                     "governance": bi("No operational state changed; human approval is required.", "未改变任何运营状态；执行前必须人工审批。")}, lang)


@router.get("/agents")
def twin_agents(lang: str = Depends(get_lang)):
    return localize(TWIN_AGENTS, lang)
