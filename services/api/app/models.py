from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String
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
