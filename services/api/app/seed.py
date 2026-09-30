from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Project, Case, KnowledgeDocument, TrainingModule

def seed(db: Session):
    if db.scalar(select(Project.id).limit(1)) is not None:
        return
    projects = [
        Project(id=1, code="MY-RAIL-A", name="Global Rail Project A", country_code="MY", country_name="Malaysia", domain="Rail", region="APAC", status="ACTIVE", risk_level="MEDIUM", languages=["English","Bahasa Melayu","中文"]),
        Project(id=2, code="ID-HWY-B", name="Trans-Nusantara Highway B", country_code="ID", country_name="Indonesia", domain="Highway", region="APAC", status="ACTIVE", risk_level="LOW", languages=["English","Bahasa Indonesia"]),
        Project(id=3, code="SA-METRO-C", name="Gulf Metro Program C", country_code="SA", country_name="Saudi Arabia", domain="Urban Rail", region="MEA", status="ACTIVE", risk_level="HIGH", languages=["English","العربية"]),
    ]
    db.add_all(projects)
    db.add_all([
        Case(id="CASE-2026-0182", project_id=1, title="Owner notice: access road, earthwork encroachment and structural crack", description="Synthetic owner notice requires a coordinated contractual and technical response within 48 hours.", type="Contract / Technical Interface", risk="HIGH", status="NEW", deadline="48 hours", source_language="English", detected_issues=["Temporary access road damage","Earthwork encroachment","Structural crack"]),
        Case(id="CASE-2026-0194", project_id=1, title="Working-at-height control gap during facade access", description="Field observation indicates a potential temporary access and fall-protection control gap.", type="HSE", risk="CRITICAL", status="UNDER_REVIEW", deadline="Immediate", source_language="Bahasa Melayu", detected_issues=["Fall protection","Access control"]),
        Case(id="CASE-2026-0201", project_id=2, title="Concrete surface defect at drainage structure", description="Quality observation requires classification and disposition workflow.", type="Quality", risk="MEDIUM", status="OPEN", deadline="72 hours", source_language="Bahasa Indonesia", detected_issues=["Surface defect","Inspection record"]),
        Case(id="CASE-2026-0209", project_id=3, title="Subcontractor method statement requires local compliance review", description="Method statement requires engineering and local HSE compliance review before approval.", type="Compliance", risk="HIGH", status="NEW", deadline="24 hours", source_language="English", detected_issues=["Method statement","Local HSE compliance"]),
    ])
    db.add_all([
        KnowledgeDocument(title="Synthetic Contract Conditions - Responsibility & Temporary Works", category="Contract", jurisdiction="Project", language="English", source_ref="CTR-A / Clause C-14.2", content="The contractor is responsible for temporary access roads expressly included within the contractor temporary works scope, subject to exclusions in the responsibility matrix.", summary="Synthetic contract clause governing temporary works and access-road responsibility."),
        KnowledgeDocument(title="Synthetic Responsibility Matrix", category="Contract", jurisdiction="Project", language="English", source_ref="RM-03 / Rev C", content="Infrastructure access road maintenance: Infrastructure Package. Building package excludes off-site village road maintenance.", summary="Synthetic responsibility matrix allocating temporary and external access obligations."),
        KnowledgeDocument(title="Synthetic Site Instruction", category="Project Record", jurisdiction="Project", language="English", source_ref="SI-028", content="Coordinate earthwork boundary with the Employer representative before further excavation adjacent to the interface zone.", summary="Synthetic site instruction on earthwork interface coordination."),
        KnowledgeDocument(title="Synthetic Concrete Crack Assessment Note", category="Engineering", jurisdiction="Project", language="English", source_ref="ENG-NOTE-017", content="Crack attribution requires location, structural element, crack width, chronology and evidence of causation before responsibility can be assigned.", summary="Engineering note requiring evidence before assigning crack responsibility."),
        KnowledgeDocument(title="Malaysia Project HSE Pack - Working at Height", category="HSE", jurisdiction="MY", language="English", source_ref="MY-HSE-WAH-01", content="Use approved access systems, fall prevention or fall arrest controls, pre-task briefing and documented inspection before work at height.", summary="Synthetic Malaysia project HSE pack for working at height."),
    ])
    db.add_all([
        TrainingModule(id="TRN-WAH-MY", title="Working at Height / Kerja di Tempat Tinggi / 高处作业", languages=["English","Bahasa Melayu","中文"], risk="HIGH", duration_min=12, modules=["Hazard recognition","Control hierarchy","Pre-use inspection","Toolbox talk","Knowledge check"]),
        TrainingModule(id="TRN-LIFT-MY", title="Lifting Operations / Operasi Mengangkat / 吊装作业", languages=["English","Bahasa Melayu","中文"], risk="HIGH", duration_min=15, modules=["Lift plan","Exclusion zone","Rigging check","Signal communication","Knowledge check"]),
    ])
    db.commit()
