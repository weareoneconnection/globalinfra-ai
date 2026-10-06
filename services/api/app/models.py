from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[dict] = mapped_column(JSON)
    country_code: Mapped[str] = mapped_column(String(8))
    country_name: Mapped[dict] = mapped_column(JSON)
    domain: Mapped[dict] = mapped_column(JSON)
    region: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE")
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW")
    # Languages used on the project are kept as native self-names
    # (glossonyms) and are intentionally not translated.
    languages: Mapped[list] = mapped_column(JSON, default=list)

class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[dict] = mapped_column(JSON)
    description: Mapped[dict] = mapped_column(JSON)
    type: Mapped[dict] = mapped_column(JSON)
    risk: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(40), default="NEW")
    deadline: Mapped[dict] = mapped_column(JSON)
    source_language: Mapped[dict] = mapped_column(JSON)
    detected_issues: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    project = relationship("Project")

class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    title: Mapped[dict] = mapped_column(JSON)
    source_type: Mapped[dict] = mapped_column(JSON)
    source_ref: Mapped[str] = mapped_column(String(160))
    excerpt: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)

class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    agent: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40), default="COMPLETED")
    summary: Mapped[dict] = mapped_column(JSON)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    title: Mapped[dict] = mapped_column(JSON)
    approver_role: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40), default="PENDING")
    risk: Mapped[str] = mapped_column(String(20), default="HIGH")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Verification(Base):
    __tablename__ = "verifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40))
    citation_score: Mapped[float] = mapped_column(Float)
    evidence_score: Mapped[float] = mapped_column(Float)
    consistency_score: Mapped[float] = mapped_column(Float)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[dict] = mapped_column(JSON)
    category: Mapped[dict] = mapped_column(JSON)
    jurisdiction: Mapped[dict] = mapped_column(JSON)
    language: Mapped[dict] = mapped_column(JSON)
    source_ref: Mapped[str] = mapped_column(String(160))
    content: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[dict] = mapped_column(JSON)

class TrainingModule(Base):
    __tablename__ = "training_modules"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[dict] = mapped_column(JSON)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    risk: Mapped[str] = mapped_column(String(20))
    duration_min: Mapped[int] = mapped_column(Integer)
    modules: Mapped[list] = mapped_column(JSON, default=list)

# --- V1.3 M1: Universal Intake Foundation ------------------------------------
# These two tables are introduced *through Alembic* (migration 0002); they are
# also part of models.Base.metadata so the offline/test ``create_all`` path in
# main.lifespan keeps producing an identical schema without running migrations.

class IntakeSubmission(Base):
    """One universal-intake event: the raw text/document that was submitted,
    the deterministic language detection result and a link to the Case it
    produced. ``input_hash`` lets a reviewer confirm the parsed text matches
    the original submission without persisting the raw blob itself."""
    __tablename__ = "intake_submissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Reference to the original input, not the input itself: "text:inline" for
    # a pasted notice, or the uploaded filename for a document.
    raw_input_ref: Mapped[str] = mapped_column(String(255))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    parsed_text: Mapped[str] = mapped_column(Text)
    detected_language: Mapped[str] = mapped_column(String(8))
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class SourceDocument(Base):
    """A file attached to an intake submission (PDF / DOCX / TXT only in M1).
    ``storage_ref`` is a content-addressed pointer (``sha256:...``) rather than
    an inline blob, matching the demo posture of not persisting raw uploads."""
    __tablename__ = "source_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intake_submission_id: Mapped[int] = mapped_column(ForeignKey("intake_submissions.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))
    storage_ref: Mapped[str] = mapped_column(String(255))
    parse_status: Mapped[str] = mapped_column(String(16), default="PARSED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
