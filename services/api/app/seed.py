from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import AIQualityRun, Connector, Organization, Project, Case, KnowledgeDocument, TrainingModule, TwinSource
from .i18n import bi
from .twin_seed import ensure_demo_twin_coverage, seed_twin
from .twin_demo import seed_synthetic_twin_sources
from .phase8 import seed_phase8
from .country_knowledge import seed_country_knowledge
from .competition import seed_competition
from .ingestion import seed_ingestion_receipts

def seed(db: Session):
    if db.scalar(select(Project.id).limit(1)) is not None:
        seed_twin(db)
        ensure_demo_twin_coverage(db)
        seed_phase7(db)
        seed_phase8(db)
        seed_synthetic_twin_sources(db)
        seed_country_knowledge(db)
        seed_competition(db)
        seed_ingestion_receipts(db)
        return
    projects = [
        Project(id=1, code="MY-RAIL-A", name=bi("Global Rail Project A", "全球轨道项目 A"), country_code="MY",
                country_name=bi("Malaysia", "马来西亚"), domain=bi("Rail", "轨道交通"), region="APAC", status="ACTIVE",
                risk_level="MEDIUM", languages=["English", "Bahasa Melayu", "中文"]),
        Project(id=2, code="ID-HWY-B", name=bi("Trans-Nusantara Highway B", "跨努桑塔拉高速公路 B"), country_code="ID",
                country_name=bi("Indonesia", "印度尼西亚"), domain=bi("Highway", "高速公路"), region="APAC", status="ACTIVE",
                risk_level="LOW", languages=["English", "Bahasa Indonesia"]),
        Project(id=3, code="SA-METRO-C", name=bi("Gulf Metro Program C", "海湾地铁项目 C"), country_code="SA",
                country_name=bi("Saudi Arabia", "沙特阿拉伯"), domain=bi("Urban Rail", "城市轨道交通"), region="MEA", status="ACTIVE",
                risk_level="HIGH", languages=["English", "العربية"]),
    ]
    db.add_all(projects)
    db.add_all([
        Case(id="CASE-2026-0182", project_id=1,
             title=bi("Owner notice: access road, earthwork encroachment and structural crack",
                       "业主通知：施工便道、土方侵占及结构裂缝问题"),
             description=bi("Synthetic fixture owner notice requires a coordinated contractual and technical response within 48 hours.",
                             "模拟夹具业主通知要求在 48 小时内给出合同与技术协同响应。"),
             type=bi("Contract / Technical Interface", "合同 / 技术接口"), risk="HIGH", status="NEW",
             deadline=bi("48 hours", "48 小时"), source_language=bi("English", "英语"),
             detected_issues=[bi("Temporary access road damage", "施工便道损坏"),
                               bi("Earthwork encroachment", "土方侵占"),
                               bi("Structural crack", "结构裂缝")]),
        Case(id="CASE-2026-0194", project_id=1,
             title=bi("Working-at-height control gap during facade access", "外立面作业高处作业管控缺口"),
             description=bi("Field observation indicates a potential temporary access and fall-protection control gap.",
                             "现场观察发现临时通道与坠落防护管控可能存在缺口。"),
             type=bi("HSE", "健康安全环保（HSE）"), risk="CRITICAL", status="NEW",
             deadline=bi("Immediate", "立即处理"), source_language=bi("Bahasa Melayu", "马来语"),
             detected_issues=[bi("Fall protection", "坠落防护"), bi("Access control", "通道管控")]),
        Case(id="CASE-2026-0201", project_id=2,
             title=bi("Concrete surface defect at drainage structure", "排水结构混凝土表面缺陷"),
             description=bi("Quality observation requires classification and disposition workflow.",
                             "质量观察问题需要进行分类并走处置流程。"),
             type=bi("Quality", "质量"), risk="MEDIUM", status="NEW",
             deadline=bi("72 hours", "72 小时"), source_language=bi("Bahasa Indonesia", "印尼语"),
             detected_issues=[bi("Surface defect", "表面缺陷"), bi("Inspection record", "检验记录")]),
        Case(id="CASE-2026-0209", project_id=3,
             title=bi("Subcontractor method statement requires local compliance review", "分包商施工方案需本地合规审查"),
             description=bi("Method statement requires engineering and local HSE compliance review before approval.",
                             "施工方案在批准前需完成工程与当地 HSE 合规审查。"),
             type=bi("Compliance", "合规"), risk="HIGH", status="NEW",
             deadline=bi("24 hours", "24 小时"), source_language=bi("English", "英语"),
             detected_issues=[bi("Method statement", "施工方案"), bi("Local HSE compliance", "当地 HSE 合规")]),
    ])
    db.add_all([
        KnowledgeDocument(
            title=bi("Synthetic Contract Conditions - Responsibility & Temporary Works", "模拟合同条件 - 责任划分与临时工程"),
            category=bi("Contract", "合同"), jurisdiction=bi("Project", "项目"), language=bi("English", "英语"),
            source_ref="CTR-A / Clause C-14.2",
            content=bi("The contractor is responsible for temporary access roads expressly included within the contractor temporary works scope, subject to exclusions in the responsibility matrix.",
                        "承包商负责明确列入其临时工程范围内的施工便道，但责任矩阵中列明的除外情形除外。"),
            summary=bi("Synthetic contract clause governing temporary works and access-road responsibility.", "关于临时工程及便道责任划分的模拟合同条款。")),
        KnowledgeDocument(
            title=bi("Synthetic Responsibility Matrix", "模拟责任矩阵"),
            category=bi("Contract", "合同"), jurisdiction=bi("Project", "项目"), language=bi("English", "英语"),
            source_ref="RM-03 / Rev C",
            content=bi("Infrastructure access road maintenance: Infrastructure Package. Building package excludes off-site village road maintenance.",
                        "基础设施便道维护：属于基础设施标段。房建标段不包含场外村道维护。"),
            summary=bi("Synthetic responsibility matrix allocating temporary and external access obligations.", "划分临时及场外通道责任的模拟责任矩阵。")),
        KnowledgeDocument(
            title=bi("Synthetic Site Instruction", "模拟现场指令"),
            category=bi("Project Record", "项目记录"), jurisdiction=bi("Project", "项目"), language=bi("English", "英语"),
            source_ref="SI-028",
            content=bi("Coordinate earthwork boundary with the Employer representative before further excavation adjacent to the interface zone.",
                        "在接口区域邻近地带继续开挖前，须与业主代表协调确认土方边界。"),
            summary=bi("Synthetic site instruction on earthwork interface coordination.", "关于土方接口协调的模拟现场指令。")),
        KnowledgeDocument(
            title=bi("Synthetic Concrete Crack Assessment Note", "模拟混凝土裂缝评估说明"),
            category=bi("Engineering", "工程"), jurisdiction=bi("Project", "项目"), language=bi("English", "英语"),
            source_ref="ENG-NOTE-017",
            content=bi("Crack attribution requires location, structural element, crack width, chronology and evidence of causation before responsibility can be assigned.",
                        "裂缝责任归属需先核实位置、结构构件、裂缝宽度、发生时序及成因证据。"),
            summary=bi("Engineering note requiring evidence before assigning crack responsibility.", "强调裂缝责任判定前须具备充分证据的工程说明。")),
        KnowledgeDocument(
            title=bi("Malaysia Project HSE Pack - Working at Height", "马来西亚项目 HSE 手册 - 高处作业"),
            category=bi("HSE", "健康安全环保（HSE）"), jurisdiction=bi("MY", "马来西亚"), language=bi("English", "英语"),
            source_ref="MY-HSE-WAH-01",
            content=bi("Use approved access systems, fall prevention or fall arrest controls, pre-task briefing and documented inspection before work at height.",
                        "高处作业前须使用经批准的通道系统、防坠落或坠落制止管控措施，并完成作业前讲解与书面检查。"),
            summary=bi("Synthetic Malaysia project HSE pack for working at height.", "马来西亚项目高处作业的模拟 HSE 手册。")),
    ])
    db.add_all([
        TrainingModule(id="TRN-WAH-MY", title=bi("Working at Height / Kerja di Tempat Tinggi / 高处作业"),
                        languages=["English", "Bahasa Melayu", "中文"], risk="HIGH", duration_min=12,
                        modules=[bi("Hazard recognition", "危险源识别"), bi("Control hierarchy", "管控层级"),
                                 bi("Pre-use inspection", "使用前检查"), bi("Toolbox talk", "班前安全讲话"),
                                 bi("Knowledge check", "知识测验")]),
        TrainingModule(id="TRN-LIFT-MY", title=bi("Lifting Operations / Operasi Mengangkat / 吊装作业"),
                        languages=["English", "Bahasa Melayu", "中文"], risk="HIGH", duration_min=15,
                        modules=[bi("Lift plan", "吊装方案"), bi("Exclusion zone", "警戒区域"),
                                 bi("Rigging check", "索具检查"), bi("Signal communication", "信号沟通"),
                                 bi("Knowledge check", "知识测验")]),
    ])
    db.commit()
    seed_twin(db)
    ensure_demo_twin_coverage(db)
    seed_phase7(db)
    seed_phase8(db)
    seed_synthetic_twin_sources(db)
    seed_country_knowledge(db)
    seed_competition(db)
    seed_ingestion_receipts(db)


def seed_phase7(db: Session):
    if db.get(Organization, "globalinfra-demo") is None:
        db.add(Organization(id="globalinfra-demo", name="GlobalInfra Demo Organization"))
    if db.scalar(select(TwinSource.id).limit(1)) is None:
        db.add_all([
            TwinSource(id="TS-MYRAIL-IFC", organization_id="globalinfra-demo", project_id=1, source_type="IFC", name="Viaduct federated model", uri="ifc://MYRAIL/STR-V12", version="REV-C", coordinate_reference_system="EPSG:32647", status="SAMPLE", checksum=None, metadata_json={"schema":"IFC4.3","objects":4182}),
            TwinSource(id="TS-MYRAIL-TILES", organization_id="globalinfra-demo", project_id=1, source_type="3D_TILES", name="Corridor geospatial tiles", uri="tiles://MYRAIL/corridor/root.json", version="2026.10", coordinate_reference_system="EPSG:4326", status="SAMPLE", checksum=None, metadata_json={"lod":"streaming","terrain":True}),
            TwinSource(id="TS-MYRAIL-IOT", organization_id="globalinfra-demo", project_id=1, source_type="IOT", name="BMS / SCADA telemetry", uri="mqtt://MYRAIL/telemetry", version="v1", coordinate_reference_system=None, status="SAMPLE", checksum=None, metadata_json={"sampling":"60s","signals":3}),
        ])
    if db.scalar(select(Connector.id).limit(1)) is None:
        db.add_all([
            Connector(id="CON-DEMO-P6", organization_id="globalinfra-demo", project_id=1, connector_type="primavera_p6", name="P6 programme adapter", status="SAMPLE", config={"endpoint_alias":"P6_DEMO","schedule_id":"MYRAIL"}),
            Connector(id="CON-DEMO-ACC", organization_id="globalinfra-demo", project_id=1, connector_type="autodesk_acc", name="ACC document adapter", status="SAMPLE", config={"endpoint_alias":"ACC_DEMO","project_ref":"MYRAIL"}),
        ])
    if db.scalar(select(AIQualityRun.id).limit(1)) is None:
        db.add_all([
            AIQualityRun(id="EVAL-DEMO-GROUNDING", organization_id="globalinfra-demo", suite="engineering-grounding", model_provider="governed-router", model_name="configured-model", status="PASSED", score=.94, thresholds={"minimum_score":.9}, metrics={"citation_precision":.97,"unsupported_claim_rate":.02}, dataset_version="2026.10"),
            AIQualityRun(id="EVAL-DEMO-ROUTING", organization_id="globalinfra-demo", suite="case-routing", model_provider="hybrid", model_name="rules-plus-llm", status="PASSED", score=.98, thresholds={"minimum_score":.95}, metrics={"domain_accuracy":.98,"risk_recall":1.0}, dataset_version="2026.10"),
        ])
    db.commit()
