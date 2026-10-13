"""Synthetic, traceable V2.0 digital-twin dataset for the pilot workspace."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .i18n import bi
from .models import (
    CommissioningItem, MaintenanceRecord, TwinEvent, TwinObject, TwinRelation,
    TwinScenario, TwinScheduleLink, TwinSensor, TwinStateHistory, utc_now,
)


def seed_twin(db: Session) -> None:
    if db.scalar(select(TwinObject.id).limit(1)) is not None:
        return

    now = utc_now()
    objects = [
        TwinObject(id="TWIN-MYRAIL", project_id=1, object_type="PROJECT", name=bi("Global Rail Project A", "全球轨道项目 A"), lifecycle_stage="construction", status="ACTIVE", health_score=86, progress=64, geometry_ref="tiles://myrail/root.json", location={"lat": 3.139, "lng": 101.687}, properties={"crs": "EPSG:4326", "modelVersion": "IFC-REV-C"}),
        TwinObject(id="TWIN-MYRAIL-V12", project_id=1, parent_id="TWIN-MYRAIL", object_type="FACILITY", name=bi("Viaduct V-12", "V-12 高架桥"), lifecycle_stage="construction", status="IN_PROGRESS", health_score=78, progress=71, geometry_ref="tiles://myrail/v12.json", location={"chainage": "CH 12+400–13+850"}, properties={"discipline": "Civil", "contractPackage": "PKG-CIV-02"}),
        TwinObject(id="TWIN-MYRAIL-V12-P47", project_id=1, parent_id="TWIN-MYRAIL-V12", object_type="ASSET", name=bi("Pier P47", "P47 桥墩"), lifecycle_stage="construction", status="INSPECTION_HOLD", health_score=62, progress=84, geometry_ref="ifc://STR-V12#P47", ifc_guid="2O1kP47GI2026", location={"chainage": "CH 12+972", "zone": "V12-Z3"}, properties={"wbs": "3.2.12.47", "material": "C50 concrete", "responsibleParty": "Civil JV"}),
        TwinObject(id="TWIN-MYRAIL-V12-P48", project_id=1, parent_id="TWIN-MYRAIL-V12", object_type="ASSET", name=bi("Pier P48", "P48 桥墩"), lifecycle_stage="construction", status="INSTALLED", health_score=91, progress=96, geometry_ref="ifc://STR-V12#P48", ifc_guid="2O1kP48GI2026", location={"chainage": "CH 13+004", "zone": "V12-Z3"}, properties={"wbs": "3.2.12.48", "material": "C50 concrete"}),
        TwinObject(id="TWIN-MYRAIL-V12-BRG47A", project_id=1, parent_id="TWIN-MYRAIL-V12-P47", object_type="COMPONENT", name=bi("Bearing P47-A", "P47-A 支座"), lifecycle_stage="commissioning", status="TEST_PENDING", health_score=74, progress=88, geometry_ref="ifc://STR-V12#BRG47A", ifc_guid="BRG47A2026GI", location={"elevation": 18.4}, properties={"manufacturer": "Synthetic Bearings Ltd", "serial": "SB-47A-003"}),
        TwinObject(id="TWIN-MYRAIL-ST04", project_id=1, parent_id="TWIN-MYRAIL", object_type="FACILITY", name=bi("Station 04", "04 号车站"), lifecycle_stage="commissioning", status="SYSTEM_TEST", health_score=88, progress=82, geometry_ref="tiles://myrail/st04.json", location={"chainage": "CH 18+220"}, properties={"contractPackage": "PKG-ST-04"}),
        TwinObject(id="TWIN-MYRAIL-ST04-HVAC", project_id=1, parent_id="TWIN-MYRAIL-ST04", object_type="SYSTEM", name=bi("Station HVAC System", "车站暖通系统"), lifecycle_stage="commissioning", status="FUNCTIONAL_TEST", health_score=83, progress=86, geometry_ref="ifc://MEP-ST04#HVAC", location={"level": "B1/L1/L2"}, properties={"systemCode": "HVAC-ST04", "assetCount": 48}),
        TwinObject(id="TWIN-MYRAIL-ST04-AHU01", project_id=1, parent_id="TWIN-MYRAIL-ST04-HVAC", object_type="ASSET", name=bi("Air Handling Unit AHU-01", "空气处理机组 AHU-01"), lifecycle_stage="operations", status="MONITORED", health_score=79, progress=100, geometry_ref="ifc://MEP-ST04#AHU01", ifc_guid="AHU01ST04GI", location={"level": "L2", "room": "MEP-204"}, properties={"manufacturer": "Synthetic MEP", "ratedFlow": "42,000 m³/h"}),
        TwinObject(id="TWIN-IDHWY-B-DRAIN21", project_id=2, object_type="ASSET", name=bi("Drainage Structure D-21", "排水结构 D-21"), lifecycle_stage="construction", status="REPAIR_IN_PROGRESS", health_score=68, progress=73, geometry_ref="ifc://IDHWY#D21", location={"chainage": "KM 88+420"}, properties={"wbs": "4.5.21"}),
        TwinObject(id="TWIN-SAMETRO-C-TUN05", project_id=3, object_type="FACILITY", name=bi("Tunnel Section T-05", "隧道区间 T-05"), lifecycle_stage="design", status="DESIGN_REVIEW", health_score=81, progress=38, geometry_ref="tiles://sametro/t05.json", location={"chainage": "CH 05+100–06+700"}, properties={"designPackage": "TUN-05"}),
    ]
    db.add_all(objects)
    db.flush()

    db.add_all([
        TwinRelation(source_id="TWIN-MYRAIL-V12-P47", target_id="TWIN-MYRAIL-V12-BRG47A", relation_type="SUPPORTS", metadata_json={"interface": "STR-BRG"}),
        TwinRelation(source_id="TWIN-MYRAIL-ST04-HVAC", target_id="TWIN-MYRAIL-ST04-AHU01", relation_type="CONTAINS", metadata_json={}),
        TwinRelation(source_id="TWIN-MYRAIL-V12-P47", target_id="TWIN-MYRAIL-V12-P48", relation_type="PRECEDES", metadata_json={"lagDays": 3}),
    ])
    db.add_all([
        TwinStateHistory(twin_id="TWIN-MYRAIL-V12-P47", previous_status="INSTALLED", status="INSPECTION_HOLD", source_system="QMS", evidence_ref="NCR-2026-084", confidence=.99, effective_at=now-timedelta(days=2)),
        TwinStateHistory(twin_id="TWIN-MYRAIL-V12-BRG47A", previous_status="INSTALLED", status="TEST_PENDING", source_system="CxMS", evidence_ref="TP-BRG-047", confidence=.96, effective_at=now-timedelta(days=1)),
        TwinStateHistory(twin_id="TWIN-MYRAIL-ST04-AHU01", previous_status="COMMISSIONED", status="MONITORED", source_system="BMS", evidence_ref="BMS-ST04-2026", confidence=.98, effective_at=now),
    ])
    db.add_all([
        TwinEvent(id="EVT-TWIN-001", twin_id="TWIN-MYRAIL-V12-P47", event_type="NCR", severity="HIGH", title=bi("Structural crack requires engineering disposition", "结构裂缝待工程处置"), domain="quality", status="OPEN", evidence_refs=["NCR-2026-084", "IR-0928", "STR-V12-042 Rev C"], occurred_at=now-timedelta(days=2)),
        TwinEvent(id="EVT-TWIN-002", twin_id="TWIN-MYRAIL-V12-BRG47A", event_type="COMMISSIONING", severity="MEDIUM", title=bi("Bearing load test awaiting access release", "支座荷载试验等待作业面释放"), domain="commissioning", status="BLOCKED", evidence_refs=["TP-BRG-047", "PTW-882"], occurred_at=now-timedelta(hours=18)),
        TwinEvent(id="EVT-TWIN-003", twin_id="TWIN-MYRAIL-ST04-AHU01", event_type="ANOMALY", severity="MEDIUM", title=bi("Vibration trend above warning threshold", "振动趋势超过预警阈值"), domain="operations", status="MONITORING", evidence_refs=["SNS-VIB-AHU01"], occurred_at=now-timedelta(hours=3)),
        TwinEvent(id="EVT-TWIN-004", twin_id="TWIN-IDHWY-B-DRAIN21", event_type="DEFECT", severity="MEDIUM", title=bi("Concrete honeycombing under repair", "混凝土蜂窝正在修复"), domain="quality", status="IN_PROGRESS", evidence_refs=["NCR-ID-021"], occurred_at=now-timedelta(days=4)),
    ])
    db.add_all([
        TwinScheduleLink(twin_id="TWIN-MYRAIL-V12-P47", wbs_code="3.2.12.47", activity_id="CIV-V12-P47", planned_progress=100, actual_progress=84, schedule_variance_days=-8, cost_code="CIV-PIER", budget=2.4, forecast=2.65),
        TwinScheduleLink(twin_id="TWIN-MYRAIL-V12-P48", wbs_code="3.2.12.48", activity_id="CIV-V12-P48", planned_progress=100, actual_progress=96, schedule_variance_days=-2, cost_code="CIV-PIER", budget=2.35, forecast=2.38),
        TwinScheduleLink(twin_id="TWIN-MYRAIL-ST04-HVAC", wbs_code="5.4.6", activity_id="MEP-ST04-HVAC-CX", planned_progress=91, actual_progress=86, schedule_variance_days=-5, cost_code="MEP-HVAC", budget=8.8, forecast=9.1),
    ])
    db.add_all([
        TwinSensor(id="SNS-VIB-AHU01", twin_id="TWIN-MYRAIL-ST04-AHU01", sensor_type="VIBRATION", unit="mm/s", threshold_warning=4.5, threshold_critical=7.1, latest_value=5.2, sampled_at=now),
        TwinSensor(id="SNS-TEMP-AHU01", twin_id="TWIN-MYRAIL-ST04-AHU01", sensor_type="BEARING_TEMP", unit="°C", threshold_warning=70, threshold_critical=85, latest_value=63.4, sampled_at=now),
        TwinSensor(id="SNS-STRAIN-P47", twin_id="TWIN-MYRAIL-V12-P47", sensor_type="STRAIN", unit="µε", threshold_warning=180, threshold_critical=240, latest_value=164, sampled_at=now),
    ])
    db.add_all([
        CommissioningItem(id="CX-BRG-047", twin_id="TWIN-MYRAIL-V12-BRG47A", system=bi("Viaduct Bearings", "高架桥支座"), test_pack="TP-BRG-047", stage="PRE_COMMISSIONING", punch_open=2, document_completeness=88, readiness=74),
        CommissioningItem(id="CX-HVAC-ST04", twin_id="TWIN-MYRAIL-ST04-HVAC", system=bi("Station HVAC", "车站暖通"), test_pack="TP-HVAC-ST04", stage="FUNCTIONAL_TEST", punch_open=7, document_completeness=92, readiness=83),
        CommissioningItem(id="CX-AHU01", twin_id="TWIN-MYRAIL-ST04-AHU01", system=bi("AHU-01", "空气处理机组 AHU-01"), test_pack="TP-AHU-001", stage="INTEGRATED_TEST", punch_open=1, document_completeness=96, readiness=91),
    ])
    db.add_all([
        MaintenanceRecord(id="WO-2026-1041", twin_id="TWIN-MYRAIL-ST04-AHU01", work_type="CONDITION_BASED", status="PLANNED", priority="HIGH", description=bi("Inspect fan alignment and bearing vibration", "检查风机对中及轴承振动"), due_at=now+timedelta(days=2)),
        MaintenanceRecord(id="WO-2026-0998", twin_id="TWIN-MYRAIL-V12-P47", work_type="STRUCTURAL_INSPECTION", status="OPEN", priority="HIGH", description=bi("Install crack gauge and verify repair response", "安装裂缝计并核验修复效果"), due_at=now+timedelta(days=1)),
    ])
    db.add_all([
        TwinScenario(id="SCN-RECOVERY-V12", project_id=1, name=bi("V12 recovery sequence", "V12 工期恢复方案"), scenario_type="SCHEDULE", assumptions={"additionalCrew": 1, "shiftHours": 10, "resequencePiers": True}, result={"daysRecovered": 5, "costDeltaM": .18, "risk": "MEDIUM", "confidence": .84}, requires_approval=True),
        TwinScenario(id="SCN-AHU-PREDICT", project_id=1, name=bi("AHU-01 predictive intervention", "AHU-01 预测性维护"), scenario_type="MAINTENANCE", assumptions={"interventionWithinDays": 2, "plannedOutageHours": 4}, result={"failureRiskReduction": 62, "avoidedDowntimeHours": 18, "costDeltaM": .02, "confidence": .88}, requires_approval=True),
        TwinScenario(id="SCN-CARBON-ST04", project_id=1, name=bi("Station energy optimization", "车站能耗优化"), scenario_type="ENERGY", assumptions={"setpointDelta": 1.5, "occupancyControl": True}, result={"annualEnergyReduction": 11.8, "carbonReductionT": 184, "comfortRisk": "LOW", "confidence": .79}, requires_approval=True),
    ])
    db.commit()


def ensure_demo_twin_coverage(db: Session) -> None:
    """Add a presentation-grade asset graph for every synthetic project.

    This is additive so existing pilot databases receive new demo coverage on
    restart without replacing any user-created twin records.
    """
    now = utc_now()
    rows = [
        TwinObject(id="TWIN-IDHWY-B", project_id=2, object_type="PROJECT", name=bi("Trans-Nusantara Highway B", "跨努桑塔拉高速公路 B"), lifecycle_stage="construction", status="ACTIVE", health_score=89, progress=57, geometry_ref="tiles://id-highway-b/tileset.json", location={"lat": -6.2088, "lng": 106.8456}, properties={"crs": "EPSG:4326", "modelVersion": "2026.10-B"}),
        TwinObject(id="TWIN-IDHWY-B-COR88", project_id=2, parent_id="TWIN-IDHWY-B", object_type="FACILITY", name=bi("Highway Corridor KM 88", "高速公路 KM 88 走廊"), lifecycle_stage="construction", status="IN_PROGRESS", health_score=84, progress=61, geometry_ref="gltf://id-highway-b/model.gltf#COR88", location={"chainage": "KM 87+800–89+200"}, properties={"package": "PKG-HWY-04"}),
        TwinObject(id="TWIN-IDHWY-B-BRG88", project_id=2, parent_id="TWIN-IDHWY-B-COR88", object_type="ASSET", name=bi("Bridge BR-88", "BR-88 桥梁"), lifecycle_stage="construction", status="DECK_WORK", health_score=86, progress=66, geometry_ref="ifc://IDHWY#BR88", ifc_guid="BR88IDHWY2026GI", location={"chainage": "KM 88+110"}, properties={"wbs": "4.2.88"}),
        TwinObject(id="TWIN-IDHWY-B-TOLL09", project_id=2, parent_id="TWIN-IDHWY-B-COR88", object_type="SYSTEM", name=bi("Toll System TS-09", "TS-09 收费系统"), lifecycle_stage="commissioning", status="FACTORY_TEST", health_score=93, progress=76, geometry_ref="gltf://id-highway-b/model.gltf#TS09", location={"chainage": "KM 89+020"}, properties={"systemCode": "ITS-TS09"}),
        TwinObject(id="TWIN-SAMETRO-C", project_id=3, object_type="PROJECT", name=bi("Gulf Metro Program C", "海湾地铁项目 C"), lifecycle_stage="design", status="ACTIVE", health_score=77, progress=38, geometry_ref="tiles://sa-metro-c/tileset.json", location={"lat": 24.7136, "lng": 46.6753}, properties={"crs": "EPSG:4326", "modelVersion": "2026.10-C"}),
        TwinObject(id="TWIN-SAMETRO-C-ST07", project_id=3, parent_id="TWIN-SAMETRO-C", object_type="FACILITY", name=bi("Underground Station 07", "07 号地下车站"), lifecycle_stage="design", status="DESIGN_COORDINATION", health_score=79, progress=42, geometry_ref="ifc://SAMETRO#ST07", ifc_guid="ST07SAMETRO2026GI", location={"chainage": "CH 06+920"}, properties={"designPackage": "ST-07"}),
        TwinObject(id="TWIN-SAMETRO-C-VENT07", project_id=3, parent_id="TWIN-SAMETRO-C-ST07", object_type="SYSTEM", name=bi("Tunnel Ventilation System TVS-07", "隧道通风系统 TVS-07"), lifecycle_stage="design", status="INTERFACE_REVIEW", health_score=72, progress=31, geometry_ref="gltf://sa-metro-c/model.gltf#TVS07", location={"zone": "ST07/TUN05"}, properties={"systemCode": "TVS-07"}),
    ]
    for row in rows:
        if db.get(TwinObject, row.id) is None:
            db.add(row)
    db.flush()
    drainage = db.get(TwinObject, "TWIN-IDHWY-B-DRAIN21")
    tunnel = db.get(TwinObject, "TWIN-SAMETRO-C-TUN05")
    if drainage:
        drainage.parent_id = "TWIN-IDHWY-B-COR88"
    if tunnel:
        tunnel.parent_id = "TWIN-SAMETRO-C"

    if db.get(TwinSensor, "SNS-WATER-DRAIN21") is None:
        db.add(TwinSensor(id="SNS-WATER-DRAIN21", twin_id="TWIN-IDHWY-B-DRAIN21", sensor_type="WATER_LEVEL", unit="mm", threshold_warning=420, threshold_critical=650, latest_value=286, sampled_at=now))
    if db.get(TwinSensor, "SNS-CONV-TUN05") is None:
        db.add(TwinSensor(id="SNS-CONV-TUN05", twin_id="TWIN-SAMETRO-C-TUN05", sensor_type="CONVERGENCE", unit="mm", threshold_warning=12, threshold_critical=18, latest_value=8.4, sampled_at=now))
    if db.scalar(select(TwinScheduleLink.id).where(TwinScheduleLink.twin_id == "TWIN-IDHWY-B-DRAIN21")) is None:
        db.add(TwinScheduleLink(twin_id="TWIN-IDHWY-B-DRAIN21", wbs_code="4.5.21", activity_id="HWY-DRAIN-21", planned_progress=80, actual_progress=73, schedule_variance_days=-4, cost_code="DRAIN", budget=1.2, forecast=1.28))
    if db.scalar(select(TwinScheduleLink.id).where(TwinScheduleLink.twin_id == "TWIN-SAMETRO-C-TUN05")) is None:
        db.add(TwinScheduleLink(twin_id="TWIN-SAMETRO-C-TUN05", wbs_code="2.3.05", activity_id="METRO-TUN-05-DES", planned_progress=46, actual_progress=38, schedule_variance_days=-11, cost_code="TUN-DES", budget=14.8, forecast=15.6))
    if db.get(CommissioningItem, "CX-TOLL-09") is None:
        db.add(CommissioningItem(id="CX-TOLL-09", twin_id="TWIN-IDHWY-B-TOLL09", system=bi("Toll System 09", "09 号收费系统"), test_pack="TP-ITS-009", stage="FACTORY_ACCEPTANCE", punch_open=3, document_completeness=78, readiness=69))
    if db.get(CommissioningItem, "CX-VENT-07") is None:
        db.add(CommissioningItem(id="CX-VENT-07", twin_id="TWIN-SAMETRO-C-VENT07", system=bi("Tunnel Ventilation 07", "07 号隧道通风"), test_pack="TP-TVS-007", stage="DESIGN_READINESS", punch_open=5, document_completeness=64, readiness=52))
    if db.get(TwinScenario, "SCN-DRAIN-RECOVERY") is None:
        db.add(TwinScenario(id="SCN-DRAIN-RECOVERY", project_id=2, name=bi("Drainage recovery sequence", "排水结构恢复方案"), scenario_type="SCHEDULE", assumptions={"additionalCrew": 1, "precastOption": True}, result={"daysRecovered": 3, "costDeltaM": .08, "confidence": .82}, requires_approval=True))
    if db.get(TwinScenario, "SCN-TUNNEL-SEQUENCE") is None:
        db.add(TwinScenario(id="SCN-TUNNEL-SEQUENCE", project_id=3, name=bi("Tunnel design release sequence", "隧道设计释放顺序"), scenario_type="DESIGN", assumptions={"parallelReview": True, "interfaceWorkshop": 2}, result={"daysRecovered": 7, "costDeltaM": .12, "confidence": .77}, requires_approval=True))
    db.commit()
