from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session
from .database import Base, SessionLocal, engine, get_db
from .models import Project, Case, Evidence, AgentRun, Approval, Verification, KnowledgeDocument, TrainingModule
from .seed import seed
from .agents import AGENTS
from .workflow import analyze_case
from .domain import LIFECYCLE_STAGES, INTELLIGENCE_DOMAINS, TRUSTED_ACTION_STAGES, PROJECT_INTELLIGENCE, DOMAIN_HEALTH, professional_domains
from .i18n import bi, get_lang, localize
from .llm import translate

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try: seed(db)
    finally: db.close()
    yield

app = FastAPI(title="GlobalInfra AI API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

@app.get('/health')
def health(): return {"status":"ok","service":"globalinfra-api","version":"1.1.0","architecture":"project-intelligence"}

class TranslateRequest(BaseModel):
    text: str
    target_lang: str = "zh"
    source_lang: str = "en"

@app.post('/i18n/translate')
async def translate_endpoint(payload: TranslateRequest):
    """Direct access to the translation-model integration (see llm.translate).
    Uses the configured OpenAI-compatible model when available, otherwise the
    deterministic offline phrase table used throughout the demo dataset."""
    translation = await translate(payload.text, payload.target_lang, payload.source_lang)
    return {"source_lang": payload.source_lang, "target_lang": payload.target_lang, "text": payload.text, "translation": translation}

@app.get('/dashboard/summary')
def dashboard(db: Session = Depends(get_db)):
    projects = db.scalar(select(func.count(Project.id))) or 0
    countries = db.scalar(select(func.count(func.distinct(Project.country_code)))) or 0
    open_cases = db.scalar(select(func.count(Case.id)).where(Case.status != 'CLOSED')) or 0
    critical = db.scalar(select(func.count(Case.id)).where(Case.risk.in_(['HIGH','CRITICAL']))) or 0
    pending = db.scalar(select(func.count(Approval.id)).where(Approval.status == 'PENDING')) or 0
    verified = 3418 + (db.scalar(select(func.count(Verification.id))) or 0)
    return {"projects":projects,"countries":countries,"open_cases":open_cases,"critical_risks":critical,"pending_approvals":pending,"verified_decisions":verified}

@app.get('/projects')
def projects(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    rows = [dict(id=p.id,code=p.code,name=p.name,country_code=p.country_code,country_name=p.country_name,domain=p.domain,region=p.region,status=p.status,risk_level=p.risk_level,languages=p.languages,**PROJECT_INTELLIGENCE.get(p.id, {})) for p in db.scalars(select(Project).order_by(Project.id))]
    return localize(rows, lang)

@app.get('/lifecycle')
def lifecycle(lang: str = Depends(get_lang)): return localize(LIFECYCLE_STAGES, lang)

@app.get('/domains')
def domains(lang: str = Depends(get_lang)):
    rows = [{**domain, **DOMAIN_HEALTH.get(domain["id"], {})} for domain in INTELLIGENCE_DOMAINS]
    return localize(rows, lang)

@app.get('/domains/professional')
def domains_professional(lang: str = Depends(get_lang)): return localize(professional_domains(), lang)

@app.get('/projects/{project_id}/workspace')
def project_workspace(project_id: int, db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    project = db.get(Project, project_id)
    if not project: raise HTTPException(404, 'Project not found')
    project_cases = list(db.scalars(select(Case).where(Case.project_id == project_id).order_by(Case.created_at.desc())))
    base = PROJECT_INTELLIGENCE.get(project_id, PROJECT_INTELLIGENCE[1])
    domain_rows = []
    for index, domain in enumerate(INTELLIGENCE_DOMAINS):
        health = DOMAIN_HEALTH[domain["id"]]
        domain_rows.append({**domain, **health, "health": max(52, health["health"] - (project_id - 1) * ((index % 3) + 1))})
    payload = {
        "project": dict(id=project.id, code=project.code, name=project.name, country_name=project.country_name, country_code=project.country_code, domain=project.domain, region=project.region, status=project.status, risk_level=project.risk_level, languages=project.languages, **base),
        "lifecycle": LIFECYCLE_STAGES,
        "domains": domain_rows,
        "cases": [dict(id=c.id,title=c.title,type=c.type,risk=c.risk,status=c.status,deadline=c.deadline) for c in project_cases],
        "trusted_action": TRUSTED_ACTION_STAGES,
    }
    return localize(payload, lang)

DIGITAL_THREAD = {
    "event": bi("Structural crack at Viaduct V-12 / Pier P47", "V-12 高架桥 / P47 桥墩结构裂缝"),
    "nodes": [
        {"type": bi("Asset", "资产"), "label": "Pier P47", "domain": "assets"},
        {"type": bi("Drawing", "图纸"), "label": "STR-V12-042 Rev C", "domain": "engineering"},
        {"type": bi("Work Package", "工作包"), "label": "WP-CIV-118", "domain": "delivery"},
        {"type": bi("Inspection", "检验"), "label": "IR-0928", "domain": "assurance"},
        {"type": bi("NCR", "不符合项"), "label": "NCR-2026-084", "domain": "assurance"},
        {"type": bi("Decision", "决策"), "label": "ENG-DEC-031", "domain": "engineering"},
        {"type": bi("Contract Impact", "合同影响"), "label": bi("Potential VO-027", "潜在变更 VO-027"), "domain": "commercial"},
        {"type": bi("Schedule Impact", "进度影响"), "label": bi("Pier cycle +6 days", "桥墩工期 +6 天"), "domain": "project"},
        {"type": bi("Corrective Action", "纠正措施"), "label": "CA-084-03", "domain": "delivery"},
        {"type": bi("Verification", "核验"), "label": bi("Pending reinspection", "待复检"), "domain": "assurance"},
    ]
}

@app.get('/digital-thread')
def digital_thread(lang: str = Depends(get_lang)): return localize(DIGITAL_THREAD, lang)

@app.get('/cases')
def cases(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    rows = db.execute(select(Case, Project.name).join(Project, Case.project_id==Project.id).order_by(Case.created_at.desc())).all()
    result = [dict(id=c.id,title=c.title,type=c.type,risk=c.risk,status=c.status,project_name=project_name,deadline=c.deadline,detected_issues=c.detected_issues) for c, project_name in rows]
    return localize(result, lang)

@app.get('/cases/{case_id}')
def case_detail(case_id: str, db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    c = db.get(Case, case_id)
    if not c: raise HTTPException(404, 'Case not found')
    project = db.get(Project, c.project_id)
    evidence = list(db.scalars(select(Evidence).where(Evidence.case_id==case_id).order_by(Evidence.id)))
    runs = list(db.scalars(select(AgentRun).where(AgentRun.case_id==case_id).order_by(AgentRun.id)))
    v = db.scalar(select(Verification).where(Verification.case_id==case_id))
    payload = {
      "id":c.id,"title":c.title,"description":c.description,"type":c.type,"risk":c.risk,"status":c.status,"deadline":c.deadline,"project_name":project.name,"source_language":c.source_language,"detected_issues":c.detected_issues,
      "evidence":[{"id":e.id,"title":e.title,"source_type":e.source_type,"source_ref":e.source_ref,"excerpt":e.excerpt,"confidence":e.confidence,"verified":e.verified} for e in evidence],
      "agent_runs":[{"id":r.id,"agent":r.agent,"status":r.status,"summary":r.summary,"duration_ms":r.duration_ms} for r in runs],
      "verification": None if not v else {"status":v.status,"citation_score":v.citation_score,"evidence_score":v.evidence_score,"consistency_score":v.consistency_score,"findings":v.findings}
    }
    return localize(payload, lang)

@app.post('/cases/{case_id}/analyze')
async def analyze(case_id: str, db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    try: result = await analyze_case(db, case_id)
    except KeyError: raise HTTPException(404, 'Case not found')
    return localize(result, lang)

@app.get('/knowledge')
def knowledge(query: str = Query(default=''), db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    stmt = select(KnowledgeDocument)
    if query:
        q = f"%{query.lower()}%"
        stmt = stmt.where(or_(func.lower(cast(KnowledgeDocument.title, String)).like(q), func.lower(cast(KnowledgeDocument.content, String)).like(q), func.lower(cast(KnowledgeDocument.category, String)).like(q)))
    rows = list(db.scalars(stmt.limit(20)))
    if not rows and query:
        rows = list(db.scalars(select(KnowledgeDocument).limit(20)))
    result = [{"id":d.id,"title":d.title,"category":d.category,"jurisdiction":d.jurisdiction,"language":d.language,"source_ref":d.source_ref,"summary":d.summary} for d in rows]
    return localize(result, lang)

@app.get('/agents')
def agents(lang: str = Depends(get_lang)): return localize(AGENTS, lang)

@app.get('/approvals')
def approvals(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    rows = list(db.scalars(select(Approval).order_by(Approval.created_at.desc())))
    result = [{"id":a.id,"case_id":a.case_id,"title":a.title,"approver_role":a.approver_role,"status":a.status,"risk":a.risk,"created_at":a.created_at.isoformat()} for a in rows]
    return localize(result, lang)

@app.post('/approvals/{approval_id}/approve')
async def approve(approval_id: int, db: Session = Depends(get_db)):
    a = db.get(Approval, approval_id)
    if not a: raise HTTPException(404, 'Approval not found')
    a.status='APPROVED'; c=db.get(Case,a.case_id); c.status='APPROVED_FOR_ACTION'
    v=db.scalar(select(Verification).where(Verification.case_id==a.case_id))
    if v:
        v.status='PASS'
        findings_en = ['Evidence-backed candidate action generated', 'Required human approval recorded', 'Trusted execution may proceed']
        v.findings = [bi(text, await translate(text, 'zh')) for text in findings_en]
    db.commit(); return {"status":"APPROVED"}

@app.post('/approvals/{approval_id}/reject')
def reject(approval_id: int, db: Session = Depends(get_db)):
    a = db.get(Approval, approval_id)
    if not a: raise HTTPException(404, 'Approval not found')
    a.status='REJECTED'; c=db.get(Case,a.case_id); c.status='REVISION_REQUIRED'; db.commit(); return {"status":"REJECTED"}

@app.get('/training')
def training(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    rows=list(db.scalars(select(TrainingModule)))
    result = [{"id":m.id,"title":m.title,"languages":m.languages,"risk":m.risk,"duration_min":m.duration_min,"modules":m.modules} for m in rows]
    return localize(result, lang)
