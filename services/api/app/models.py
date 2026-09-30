from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    country_code: Mapped[str] = mapped_column(String(8))
    country_name: Mapped[str] = mapped_column(String(80))
    domain: Mapped[str] = mapped_column(String(80))
    region: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE")
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW")
    languages: Mapped[list] = mapped_column(JSON, default=list)

class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(80))
    risk: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(40), default="NEW")
    deadline: Mapped[str] = mapped_column(String(80))
    source_language: Mapped[str] = mapped_column(String(20), default="en")
    detected_issues: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    project = relationship("Project")

class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(80))
    source_ref: Mapped[str] = mapped_column(String(160))
    excerpt: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)

class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    agent: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40), default="COMPLETED")
    summary: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    approver_role: Mapped[str] = mapped_column(String(120))
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
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(80))
    jurisdiction: Mapped[str] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(20))
    source_ref: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)

class TrainingModule(Base):
    __tablename__ = "training_modules"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    languages: Mapped[list] = mapped_column(JSON, default=list)
    risk: Mapped[str] = mapped_column(String(20))
    duration_min: Mapped[int] = mapped_column(Integer)
    modules: Mapped[list] = mapped_column(JSON, default=list)
