import asyncio
import hashlib
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session
from .database import Base, SessionLocal, engine, get_db
from .models import (
    Project, Case, Claim, Evidence, AgentRun, Approval, Verification, Action,
    Artifact, ExecutionReceipt, VerificationReceipt, KnowledgeDocument, utc_now,
    TrainingModule, IntakeSubmission, SourceDocument,
)
from .seed import seed
from .agents import AGENTS
from .workflow import analyze_case, AGENTS_BY_ID
from .domain import LIFECYCLE_STAGES, INTELLIGENCE_DOMAINS, TRUSTED_ACTION_STAGES, PROJECT_INTELLIGENCE, DOMAIN_HEALTH, professional_domains
from .i18n import bi, get_lang, localize
from .llm import LLMError, reset_routing_trace, routing_status, routing_trace, translate
from .classify import classify_text
from .intake import build_intake_result, detect_language, LANGUAGE_DISPLAY
from .llm_classify import classify_text_llm
from .llm_extract import extract_fields_llm
from .documents import extract_text, UnsupportedDocument
from .security import Principal, api_key_gate, get_principal, require_project, require_roles
from .config import settings
from .operations import metrics_response, production_controls
from .phase7 import router as phase7_router
from .governed_execution import (
    GovernedExecutionError, artifact_payload, close_action, execute_action, verify_action,
)
from .twin import router as twin_router
from .twin_demo import router as twin_demo_router
from .phase8 import router as phase8_router
from .country_knowledge import router as country_knowledge_router
from .competition import router as competition_router
from .ingestion import receipt_payload, record_ingestion_receipt, router as ingestion_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try: seed(db)
    finally: db.close()
    yield

app = FastAPI(title="GlobalInfra AI API", version="4.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "Accept-Language"],
)
# Off by default (see app.security / app.config.settings.require_api_key);
# turning it on in a pilot deployment needs only an env var, no code change.
app.middleware("http")(api_key_gate)
app.middleware("http")(production_controls)
app.include_router(twin_router)
app.include_router(twin_demo_router)
app.include_router(phase8_router)
app.include_router(phase7_router)
app.include_router(country_knowledge_router)
app.include_router(competition_router)
app.include_router(ingestion_router)

@app.get('/health')
def health(): return {"status":"ok","service":"globalinfra-api","version":"4.3.0","product_version":"V4.3","architecture":"unified-ingestion-control-plane"}

@app.get('/livez')
def livez(): return {"status": "alive"}

@app.get('/readyz')
def readyz(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ready", "database": "ok", "auth_mode": settings.auth_mode, "llm_mode": settings.llm_mode}

@app.get('/metrics', include_in_schema=False)
def metrics(): return metrics_response()

class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    target_lang: str = "zh"
    source_lang: str = "en"
    model_route: Literal["local", "openai", "auto"] | None = None
    data_classification: Literal["public", "internal", "restricted"] = "internal"

@app.get('/llm/status')
def llm_status():
    return routing_status()

@app.post('/i18n/translate')
async def translate_endpoint(payload: TranslateRequest):
    """Direct access to the translation-model integration (see llm.translate).
    Uses the configured OpenAI-compatible model when available, otherwise the
    deterministic offline phrase table used throughout the demo dataset."""
    reset_routing_trace()
    routing = {}
    if payload.model_route is not None:
        routing["route"] = payload.model_route
    if payload.data_classification != "internal":
        routing["sensitivity"] = payload.data_classification
    try:
        translation = await translate(
            payload.text, payload.target_lang, payload.source_lang, **routing
        )
    except LLMError as exc: raise HTTPException(502, str(exc))
    return {
        "source_lang": payload.source_lang,
        "target_lang": payload.target_lang,
        "text": payload.text,
        "translation": translation,
        "model_routing": {
            "requested": payload.model_route or settings.llm_mode,
            "data_classification": payload.data_classification,
            "trace": routing_trace(),
        },
    }

class ClassifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)

@app.post('/cases/classify')
def classify_endpoint(payload: ClassifyRequest):
    """Deterministic, rule-based case classification for arbitrary free-text
    field observations / owner notices (see app.classify.classify_text).
    This is what the evaluation harness in evals/run_eval.py exercises, and
    is independent of the seeded demo case dataset."""
    return {"text": payload.text, **classify_text(payload.text)}

# --- V1.3 M1: Universal Intake ----------------------------------------------

class IntakeTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500_000)
    language: str | None = None  # optional hint; auto-detected when omitted
    project_id: int | None = Field(default=None, gt=0)
    entry_type: Literal["text", "work_order"] = "text"
    model_route: Literal["local", "openai", "auto"] | None = None
    data_classification: Literal["public", "internal", "restricted"] = "internal"

def _select_project_id(db: Session, country_code: str | None) -> tuple[int | None, float]:
    """Route only when the detected country resolves to a real project.

    There is intentionally no lowest-id fallback: an unidentified intake must
    remain unassigned until a human confirms its project.
    """
    if country_code:
        pid = db.scalar(select(Project.id).where(Project.country_code == country_code).order_by(Project.id).limit(1))
        if pid:
            return pid, 0.95
    return None, 0.0

def _case_title(text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), text.strip())
    return (first_line[:117] + "…") if len(first_line) > 118 else (first_line or "Intake submission")


@dataclass(frozen=True)
class SourceUpload:
    filename: str
    file_type: str
    storage_ref: str
    content_type: str | None
    content: bytes


async def _intake_pipeline(db: Session, text: str, lang: str, raw_input_ref: str,
                           language_hint: str | None, source_file: SourceUpload | None,
                           model_route: str | None = None, data_classification: str = "internal",
                           organization_id: str = "globalinfra-demo",
                           project_id_override: int | None = None,
                           entry_type: str = "text"):
    """Shared core for both intake endpoints: classify (Layer 1) + enrich,
    create a Case, persist the intake submission (and optional source
    document), then run the real analysis workflow. Returns the localized
    response payload."""
    reset_routing_trace()
    if not (text or "").strip():
        raise HTTPException(422, "Intake text is empty after extraction; nothing to classify.")

    # Layer 2 (M2): LLM-refined {type, risk} when a model is configured, else
    # the deterministic Layer-1 rules. Layer 3 (M3): LLM-refined, vocabulary-
    # constrained + text-grounded country/issues/entities, else None so
    # build_intake_result keeps its deterministic extraction. The two layers
    # share only the raw ``text`` and have no data dependency on each other, so
    # dispatch both LLM round-trips concurrently (M6): real-model latency drops
    # from classify+extract to max(classify, extract). Each coroutine already
    # catches its own LLMError and degrades independently (classify -> rules,
    # extract -> None), so gather never sees a raised exception; offline (no key)
    # both layers are inert and return at once, leaving the result byte-for-byte
    # the M1 output.
    classification, extraction = await asyncio.gather(
        classify_text_llm(text, model_route, data_classification),
        extract_fields_llm(text, model_route, data_classification),
    )
    result = build_intake_result(text, language_hint, classification=classification, extraction=extraction)
    detected_lang = result["language"]
    if project_id_override is not None:
        project_id, project_routing_confidence = project_id_override, 1.0
        project_routing_source = "USER_CONFIRMED"
    else:
        project_id, project_routing_confidence = _select_project_id(db, result["country"])
        project_routing_source = "COUNTRY_AUTO_ROUTE" if project_id is not None else "NEEDS_CONFIRMATION"
    case_id = f"CASE-INTAKE-{uuid.uuid4().hex[:8].upper()}"
    title = _case_title(text)

    routing_status = "ROUTED" if project_id is not None else "NEEDS_PROJECT_CONFIRMATION"
    result["project_routing_status"] = routing_status
    result["project_routing_confidence"] = project_routing_confidence
    result["project_routing_source"] = project_routing_source
    case = Case(
        id=case_id, project_id=project_id,
        title=bi(title), description=bi(text[:600] + ("…" if len(text) > 600 else "")),
        type=result["case_type_label"], risk=result["risk"], status="NEW" if project_id is not None else routing_status,
        deadline=result["deadline"] or bi("Not specified", "未指定"),
        source_language=LANGUAGE_DISPLAY.get(detected_lang, bi(detected_lang)),
        detected_issues=result["issues"],
        project_routing_confidence=project_routing_confidence,
        routing_status=routing_status,
    )
    db.add(case)

    input_hash = (
        source_file.storage_ref.removeprefix("sha256:")
        if source_file is not None
        else hashlib.sha256(text.encode("utf-8")).hexdigest()
    )
    submission = IntakeSubmission(
        raw_input_ref=raw_input_ref,
        input_hash=input_hash,
        parsed_text=text, detected_language=detected_lang, case_id=case_id,
    )
    db.add(submission)
    db.flush()  # assign submission.id before linking a source document

    if source_file is not None:
        db.add(SourceDocument(
            intake_submission_id=submission.id, filename=source_file.filename,
            file_type=source_file.file_type, storage_ref=source_file.storage_ref,
            parse_status="PARSED", content_type=source_file.content_type,
            byte_size=len(source_file.content), original_content=source_file.content,
        ))
    receipt = record_ingestion_receipt(
        db, organization_id=organization_id, project_id=project_id,
        channel="document_correspondence" if source_file is not None else "event_work_order",
        source_type=source_file.file_type if source_file is not None else entry_type,
        status="ACCEPTED", target_type="Case", target_id=case_id,
        checksum=submission.input_hash,
        validation_summary={
            "language": detected_lang, "case_type": result["case_type"],
            "risk": result["risk"], "project_routing_status": routing_status,
            "project_routing_source": project_routing_source,
        },
        lineage={
            "raw_input_ref": raw_input_ref, "submission_id": submission.id,
            "data_classification": data_classification,
            **({"raw_preserved": True, "storage_ref": source_file.storage_ref}
               if source_file is not None else {}),
        },
    )
    db.commit()
    db.refresh(receipt)

    try:
        analysis = await analyze_case(db, case_id, model_route, data_classification)
    except LLMError as exc:
        raise HTTPException(502, str(exc))

    payload = {
        "submission_id": submission.id,
        "case_id": case_id,
        "ingestion_receipt": receipt_payload(receipt),
        "intake": result,
        "specialist_team": [
            {"id": agent_id, "name": AGENTS_BY_ID[agent_id]["name"]}
            for agent_id in result["recommended_agents"]
        ],
        "analysis": analysis,
        "model_routing": {
            "requested": model_route or settings.llm_mode,
            "data_classification": data_classification,
            "trace": routing_trace(),
        },
    }
    return localize(payload, lang)


def _queue_document_for_ocr(
    db: Session, *, source_file: SourceUpload, lang: str,
    data_classification: str, organization_id: str,
    model_route: str | None,
):
    """Accept a valid image-only document without inventing extracted text.

    The source remains a document, its original bytes and checksum are
    preserved, and the standard receipt explicitly records that OCR is the
    next processing step.  A Case is intentionally not created until text is
    available for classification and evidence-grounded analysis.
    """
    reset_routing_trace()
    checksum = source_file.storage_ref.removeprefix("sha256:")
    submission = IntakeSubmission(
        raw_input_ref=source_file.filename,
        input_hash=checksum,
        parsed_text="",
        detected_language="und",
        case_id=None,
    )
    db.add(submission)
    db.flush()
    document = SourceDocument(
        intake_submission_id=submission.id,
        filename=source_file.filename,
        file_type=source_file.file_type,
        storage_ref=source_file.storage_ref,
        parse_status="OCR_REQUIRED",
        content_type=source_file.content_type,
        byte_size=len(source_file.content),
        original_content=source_file.content,
    )
    db.add(document)
    db.flush()
    receipt = record_ingestion_receipt(
        db,
        organization_id=organization_id,
        channel="document_correspondence",
        source_type=source_file.file_type,
        status="OCR_REQUIRED",
        target_type="SourceDocument",
        target_id=document.id,
        checksum=checksum,
        validation_summary={
            "file_valid": True,
            "text_extracted": False,
            "ocr_required": True,
            "file_type": source_file.file_type,
            "byte_size": len(source_file.content),
        },
        lineage={
            "raw_input_ref": source_file.filename,
            "submission_id": submission.id,
            "data_classification": data_classification,
            "raw_preserved": True,
            "storage_ref": source_file.storage_ref,
        },
    )
    db.commit()
    db.refresh(receipt)
    return localize({
        "submission_id": submission.id,
        "case_id": None,
        "ingestion_receipt": receipt_payload(receipt),
        "document": {
            "id": document.id,
            "filename": document.filename,
            "file_type": document.file_type,
            "parse_status": document.parse_status,
            "content_type": document.content_type,
            "byte_size": document.byte_size,
            "original_preserved": True,
        },
        "intake": {
            "status": "OCR_REQUIRED",
            "text_extracted": False,
            "ocr_required": True,
            "message": bi(
                "The original document was accepted and preserved. OCR is required before classification and case creation.",
                "原始文档已接收并留存；完成 OCR 后再进入分类与工单生成。",
            ),
        },
        "specialist_team": [],
        "analysis": None,
        "model_routing": {
            "requested": model_route or settings.llm_mode,
            "data_classification": data_classification,
            "trace": routing_trace(),
        },
    }, lang)

@app.post('/intake/text')
async def intake_text(
    payload: IntakeTextRequest, db: Session = Depends(get_db),
    lang: str = Depends(get_lang), principal: Principal = Depends(get_principal),
):
    """Universal intake for free-text field observations / owner notices /
    letters. Classifies deterministically (Layer 1), creates a Case, and runs
    the real retrieval-grounded analysis workflow, returning the Case id and
    the specialist team that was selected for it."""
    if payload.project_id is not None:
        require_project(principal, payload.project_id)
        if not db.get(Project, payload.project_id):
            raise HTTPException(404, "Project not found")
    return await _intake_pipeline(
        db, payload.text, lang,
        raw_input_ref="work_order:manual" if payload.entry_type == "work_order" else "text:inline",
        language_hint=payload.language, source_file=None,
        model_route=payload.model_route, data_classification=payload.data_classification,
        organization_id=principal.organization_id,
        project_id_override=payload.project_id, entry_type=payload.entry_type,
    )

@app.post('/intake/document')
async def intake_document(
    file: UploadFile = File(...),
    model_route: Literal["local", "openai", "auto"] | None = Query(default=None),
    data_classification: Literal["public", "internal", "restricted"] = Query(default="internal"),
    db: Session = Depends(get_db),
    lang: str = Depends(get_lang),
    principal: Principal = Depends(get_principal),
):
    """Universal intake for an uploaded PDF / DOCX / TXT document.

    Text-bearing documents enter the analysis pipeline immediately. Valid
    scanned/image-only files are preserved and receive an ``OCR_REQUIRED``
    receipt instead of being rejected or misclassified.
    """
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, f"Upload exceeds the {settings.max_upload_bytes}-byte limit.")
    if not content:
        raise HTTPException(422, "Uploaded document is empty.")
    try:
        text, file_type = extract_text(file.filename, content, file.content_type)
    except UnsupportedDocument as exc:
        raise HTTPException(400, str(exc))
    storage_ref = f"sha256:{hashlib.sha256(content).hexdigest()}"
    source_file = SourceUpload(
        filename=file.filename or "upload",
        file_type=file_type,
        storage_ref=storage_ref,
        content_type=file.content_type,
        content=content,
    )
    if not text.strip():
        if file_type == "txt":
            raise HTTPException(422, "Uploaded TXT document does not contain text.")
        return _queue_document_for_ocr(
            db,
            source_file=source_file,
            lang=lang,
            data_classification=data_classification,
            organization_id=principal.organization_id,
            model_route=model_route,
        )
    return await _intake_pipeline(
        db, text, lang, raw_input_ref=file.filename or "upload",
        language_hint=None, source_file=source_file,
        model_route=model_route, data_classification=data_classification,
        organization_id=principal.organization_id,
    )

@app.get('/dashboard/summary')
def dashboard(db: Session = Depends(get_db)):
    projects = db.scalar(select(func.count(Project.id))) or 0
    countries = db.scalar(select(func.count(func.distinct(Project.country_code)))) or 0
    open_cases = db.scalar(select(func.count(Case.id)).where(Case.status != 'CLOSED')) or 0
    critical = db.scalar(select(func.count(Case.id)).where(Case.risk.in_(['HIGH','CRITICAL']))) or 0
    pending = db.scalar(select(func.count(Approval.id)).where(Approval.status == 'PENDING')) or 0
    verified = db.scalar(select(func.count(VerificationReceipt.id)).where(VerificationReceipt.status == "VERIFIED")) or 0
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
    rows = db.execute(select(Case, Project.name).join(Project, Case.project_id==Project.id, isouter=True).order_by(Case.created_at.desc())).all()
    result = [dict(id=c.id,title=c.title,type=c.type,risk=c.risk,status=c.status,project_name=project_name,deadline=c.deadline,detected_issues=c.detected_issues,routing_status=c.routing_status,project_routing_confidence=c.project_routing_confidence) for c, project_name in rows]
    return localize(result, lang)

@app.get('/cases/{case_id}')
def case_detail(case_id: str, db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    c = db.get(Case, case_id)
    if not c: raise HTTPException(404, 'Case not found')
    project = db.get(Project, c.project_id) if c.project_id is not None else None
    evidence = list(db.scalars(select(Evidence).where(Evidence.case_id==case_id).order_by(Evidence.id)))
    claims = list(db.scalars(select(Claim).where(Claim.case_id==case_id).order_by(Claim.id)))
    runs = list(db.scalars(select(AgentRun).where(AgentRun.case_id==case_id).order_by(AgentRun.id)))
    v = db.scalar(select(Verification).where(Verification.case_id==case_id))
    action = db.scalar(select(Action).where(Action.case_id == case_id).order_by(Action.created_at.desc()))
    execution = db.scalar(select(ExecutionReceipt).where(ExecutionReceipt.case_id == case_id).order_by(ExecutionReceipt.started_at.desc()))
    verification_receipt = db.scalar(select(VerificationReceipt).where(VerificationReceipt.case_id == case_id).order_by(VerificationReceipt.verified_at.desc()))
    artifact = db.scalar(select(Artifact).where(Artifact.action_id == action.id)) if action else None
    payload = {
      "id":c.id,"title":c.title,"description":c.description,"type":c.type,"risk":c.risk,"status":c.status,"deadline":c.deadline,"project_name":None if project is None else project.name,"source_language":c.source_language,"detected_issues":c.detected_issues,
      "routing_status":c.routing_status,"project_routing_confidence":c.project_routing_confidence,
      "claims":[{"id":claim.id,"statement":claim.statement,"status":claim.status} for claim in claims],
      "evidence":[{"id":e.id,"claim_id":e.claim_id,"title":e.title,"source_type":e.source_type,"source_ref":e.source_ref,"excerpt":e.excerpt,"confidence":e.confidence,"verified":e.verified} for e in evidence],
      "agent_runs":[{"id":r.id,"agent":r.agent,"status":r.status,"summary":r.summary,"duration_ms":r.duration_ms} for r in runs],
      "verification": None if not v else {"status":v.status,"citation_score":v.citation_score,"evidence_score":v.evidence_score,"consistency_score":v.consistency_score,"findings":v.findings},
      "action": None if not action else {"id":action.id,"action_type":action.action_type,"status":action.status,"approval_id":action.approval_id,"evidence_refs":action.evidence_refs,"input_digest":action.input_digest,"output_digest":action.output_digest,"artifact_ref":action.artifact_ref},
      "execution_receipt": None if not execution else {"id":execution.id,"case_id":execution.case_id,"action_id":execution.action_id,"approval_id":execution.approval_id,"executor":execution.executor,"action_type":execution.action_type,"started_at":execution.started_at.isoformat(),"completed_at":execution.completed_at.isoformat() if execution.completed_at else None,"status":execution.status,"evidence_refs":execution.evidence_refs,"input_digest":execution.input_digest,"output_digest":execution.output_digest,"artifact_ref":execution.artifact_ref},
      "verification_receipt": None if not verification_receipt else {"id":verification_receipt.id,"status":verification_receipt.status,"checks":verification_receipt.checks,"findings":verification_receipt.findings,"artifact_ref":verification_receipt.artifact_ref,"artifact_digest":verification_receipt.artifact_digest,"verified_at":verification_receipt.verified_at.isoformat()},
      "artifact": None if artifact is None else {"id":artifact.id,"artifact_ref":artifact.artifact_ref,"artifact_type":artifact.artifact_type,"media_type":artifact.media_type,"digest":artifact.digest},
    }
    return localize(payload, lang)

@app.post('/cases/{case_id}/analyze')
async def analyze(
    case_id: str,
    model_route: Literal["local", "openai", "auto"] | None = Query(default=None),
    data_classification: Literal["public", "internal", "restricted"] = Query(default="internal"),
    db: Session = Depends(get_db),
    lang: str = Depends(get_lang),
):
    reset_routing_trace()
    try: result = await analyze_case(db, case_id, model_route, data_classification)
    except KeyError: raise HTTPException(404, 'Case not found')
    except LLMError as exc: raise HTTPException(502, str(exc))
    result["model_routing"] = {
        "requested": model_route or settings.llm_mode,
        "data_classification": data_classification,
        "trace": routing_trace(),
    }
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
    result = [{"id":a.id,"case_id":a.case_id,"action_id":a.action_id,"title":a.title,"approver_role":a.approver_role,"status":a.status,"risk":a.risk,"created_at":a.created_at.isoformat()} for a in rows]
    return localize(result, lang)

@app.post('/approvals/{approval_id}/approve')
def approve(approval_id: int, principal: Principal = Depends(require_roles("approver")), db: Session = Depends(get_db)):
    a = db.get(Approval, approval_id)
    if not a: raise HTTPException(404, 'Approval not found')
    if a.status == "REJECTED":
        raise HTTPException(409, "Rejected approval requires rework before it can be approved.")
    a.status = "APPROVED"
    a.decided_by = principal.subject
    a.decided_at = utc_now()
    action = db.get(Action, a.action_id) if a.action_id else db.scalar(select(Action).where(Action.case_id == a.case_id))
    case = db.get(Case, a.case_id)
    approvals_for_case = list(db.scalars(select(Approval).where(Approval.case_id == a.case_id)))
    if action and all(item.status == "APPROVED" for item in approvals_for_case):
        action.status = "APPROVED"
        action.approved_at = utc_now()
        case.status = "APPROVED"
    else:
        case.status = "AWAITING_APPROVAL"
    db.commit()
    return {"status": "APPROVED", "case_status": case.status, "action_id": None if action is None else action.id, "action_status": None if action is None else action.status}

@app.post('/approvals/{approval_id}/reject')
def reject(approval_id: int, principal: Principal = Depends(require_roles("approver")), db: Session = Depends(get_db)):
    a = db.get(Approval, approval_id)
    if not a: raise HTTPException(404, 'Approval not found')
    a.status = 'REJECTED'
    a.decided_by = principal.subject
    a.decided_at = utc_now()
    action = db.get(Action, a.action_id) if a.action_id else db.scalar(select(Action).where(Action.case_id == a.case_id))
    c = db.get(Case, a.case_id)
    c.status = 'REJECTED'
    if action:
        action.status = 'REJECTED'
    db.commit()
    return {"status": "REJECTED", "case_status": c.status, "action_id": None if action is None else action.id}

class ExecutionRequest(BaseModel):
    executor: str = Field(default="governed.document.generate", min_length=1, max_length=120)


class VerificationRequest(BaseModel):
    verifier: str = Field(default="independent.verifier", min_length=1, max_length=120)


def _governed_error(exc: GovernedExecutionError) -> HTTPException:
    return HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.message})


def _action_row(action: Action, db: Session) -> dict:
    execution = db.scalar(select(ExecutionReceipt).where(ExecutionReceipt.action_id == action.id))
    verification = db.scalar(select(VerificationReceipt).where(VerificationReceipt.action_id == action.id))
    return {
        "id": action.id,
        "case_id": action.case_id,
        "approval_id": action.approval_id,
        "action_type": action.action_type,
        "status": action.status,
        "evidence_refs": action.evidence_refs,
        "input_digest": action.input_digest,
        "output_digest": action.output_digest,
        "artifact_ref": action.artifact_ref,
        "execution_receipt_id": None if execution is None else execution.id,
        "verification_receipt_id": None if verification is None else verification.id,
        "created_at": action.created_at.isoformat(),
    }


@app.get('/actions')
def actions(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    return localize([_action_row(action, db) for action in db.scalars(select(Action).order_by(Action.created_at.desc()))], lang)


@app.get('/actions/{action_id}')
def action_detail(action_id: str, db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    action = db.get(Action, action_id)
    if not action:
        raise HTTPException(404, "Action not found")
    return localize(_action_row(action, db), lang)


@app.post('/actions/{action_id}/execute')
def execute(
    action_id: str, payload: ExecutionRequest | None = None,
    principal: Principal = Depends(require_roles("engineer", "project_manager")),
    db: Session = Depends(get_db),
):
    try:
        return execute_action(db, action_id, payload.executor if payload else principal.subject)
    except GovernedExecutionError as exc:
        raise _governed_error(exc) from exc


@app.post('/cases/{case_id}/execute')
def execute_case(
    case_id: str, payload: ExecutionRequest | None = None,
    principal: Principal = Depends(require_roles("engineer", "project_manager")),
    db: Session = Depends(get_db),
):
    action = db.scalar(select(Action).where(Action.case_id == case_id).order_by(Action.created_at.desc()))
    if not action:
        raise HTTPException(404, "No governed action exists for case")
    try:
        result = execute_action(db, action.id, payload.executor if payload else principal.subject)
        result["case_id"] = case_id
        return result
    except GovernedExecutionError as exc:
        raise _governed_error(exc) from exc


@app.post('/actions/{action_id}/verify')
def verify(
    action_id: str, payload: VerificationRequest | None = None,
    principal: Principal = Depends(require_roles("verifier")), db: Session = Depends(get_db),
):
    try:
        return verify_action(db, action_id, payload.verifier if payload else principal.subject)
    except GovernedExecutionError as exc:
        raise _governed_error(exc) from exc


@app.post('/cases/{case_id}/verify')
def verify_case(
    case_id: str, payload: VerificationRequest | None = None,
    principal: Principal = Depends(require_roles("verifier")), db: Session = Depends(get_db),
):
    action = db.scalar(select(Action).where(Action.case_id == case_id).order_by(Action.created_at.desc()))
    if not action:
        raise HTTPException(404, "No governed action exists for case")
    try:
        return verify_action(db, action.id, payload.verifier if payload else principal.subject)
    except GovernedExecutionError as exc:
        raise _governed_error(exc) from exc


@app.post('/actions/{action_id}/close')
def close(
    action_id: str, principal: Principal = Depends(require_roles("project_manager")),
    db: Session = Depends(get_db),
):
    try:
        return close_action(db, action_id)
    except GovernedExecutionError as exc:
        raise _governed_error(exc) from exc


@app.get('/artifacts/{artifact_id}')
def artifact(artifact_id: str, db: Session = Depends(get_db)):
    artifact_row = db.get(Artifact, artifact_id)
    if not artifact_row:
        raise HTTPException(404, "Artifact not found")
    return artifact_payload(artifact_row)


@app.get('/execution-receipts/{receipt_id}')
def execution_receipt(receipt_id: str, db: Session = Depends(get_db)):
    receipt = db.get(ExecutionReceipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "Execution receipt not found")
    artifact_row = db.scalar(select(Artifact).where(Artifact.action_id == receipt.action_id))
    return {
        "id": receipt.id, "case_id": receipt.case_id, "action_id": receipt.action_id,
        "approval_id": receipt.approval_id, "executor": receipt.executor,
        "action_type": receipt.action_type, "started_at": receipt.started_at.isoformat(),
        "completed_at": receipt.completed_at.isoformat() if receipt.completed_at else None,
        "status": receipt.status, "evidence_refs": receipt.evidence_refs,
        "input_digest": receipt.input_digest, "output_digest": receipt.output_digest,
        "artifact_ref": receipt.artifact_ref,
        "artifact": None if artifact_row is None else artifact_payload(artifact_row),
    }


@app.get('/verification-receipts/{receipt_id}')
def verification_receipt(receipt_id: str, db: Session = Depends(get_db)):
    receipt = db.get(VerificationReceipt, receipt_id)
    if not receipt:
        raise HTTPException(404, "Verification receipt not found")
    return {
        "id": receipt.id, "case_id": receipt.case_id, "action_id": receipt.action_id,
        "execution_receipt_id": receipt.execution_receipt_id, "approval_id": receipt.approval_id,
        "status": receipt.status, "findings": receipt.findings, "checks": receipt.checks,
        "evidence_refs": receipt.evidence_refs, "artifact_ref": receipt.artifact_ref,
        "artifact_digest": receipt.artifact_digest, "verified_at": receipt.verified_at.isoformat(),
    }


@app.get('/training')
def training(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    rows=list(db.scalars(select(TrainingModule)))
    result = [{"id":m.id,"title":m.title,"languages":m.languages,"risk":m.risk,"duration_min":m.duration_min,"modules":m.modules} for m in rows]
    return localize(result, lang)
