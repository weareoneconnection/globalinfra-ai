from datetime import UTC, datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def utc_now() -> datetime:
    """Naive UTC for database columns without triggering utcnow deprecation."""
    return datetime.now(UTC).replace(tzinfo=None)

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
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    title: Mapped[dict] = mapped_column(JSON)
    description: Mapped[dict] = mapped_column(JSON)
    type: Mapped[dict] = mapped_column(JSON)
    risk: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(40), default="NEW")
    deadline: Mapped[dict] = mapped_column(JSON)
    source_language: Mapped[dict] = mapped_column(JSON)
    detected_issues: Mapped[list] = mapped_column(JSON, default=list)
    project_routing_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    routing_status: Mapped[str] = mapped_column(String(40), default="ROUTED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    project = relationship("Project")

class Claim(Base):
    """A case-scoped assertion that can be traced to one or more evidence rows."""
    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    statement: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="UNVERIFIED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id"), nullable=True, index=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    title: Mapped[dict] = mapped_column(JSON)
    approver_role: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40), default="PENDING")
    risk: Mapped[str] = mapped_column(String(20), default="HIGH")
    action_id: Mapped[str | None] = mapped_column(ForeignKey("actions.id"), nullable=True, index=True)
    decided_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Action(Base):
    """A governed, idempotent intent to invoke one real tool."""
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("approvals.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), default="AWAITING_APPROVAL", index=True)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    input_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Artifact(Base):
    """Content-addressed output produced by a governed action."""
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("actions.id"), unique=True, index=True)
    artifact_ref: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    artifact_type: Mapped[str] = mapped_column(String(80))
    media_type: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class ExecutionReceipt(Base):
    """Immutable audit record for one real tool invocation."""
    __tablename__ = "execution_receipts"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("actions.id"), unique=True, index=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("approvals.id"), index=True)
    executor: Mapped[str] = mapped_column(String(120))
    action_type: Mapped[str] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    input_digest: Mapped[str] = mapped_column(String(64))
    output_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class VerificationReceipt(Base):
    """Independent post-execution verification, distinct from analysis scoring."""
    __tablename__ = "verification_receipts"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("actions.id"), unique=True, index=True)
    execution_receipt_id: Mapped[str] = mapped_column(ForeignKey("execution_receipts.id"), unique=True, index=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("approvals.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    checks: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    artifact_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    artifact_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Verification(Base):
    __tablename__ = "verifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40))
    citation_score: Mapped[float] = mapped_column(Float)
    evidence_score: Mapped[float] = mapped_column(Float)
    consistency_score: Mapped[float] = mapped_column(Float)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

# --- V3.0 / Phase 7: production-pilot operating plane -----------------------

class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Identity(Base):
    """OIDC subject mapped to a GlobalInfra organization and project scope."""
    __tablename__ = "identities"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    issuer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    roles: Mapped[list] = mapped_column(JSON, default=list)
    project_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(255), index=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(160), index=True)
    resource_type: Mapped[str] = mapped_column(String(80), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    outcome: Mapped[str] = mapped_column(String(24), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class FieldObservation(Base):
    __tablename__ = "field_observations"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    twin_id: Mapped[str | None] = mapped_column(ForeignKey("twin_objects.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[dict] = mapped_column(JSON, default=dict)
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    reporter_id: Mapped[str] = mapped_column(String(255), index=True)
    sync_status: Mapped[str] = mapped_column(String(24), default="SYNCED", index=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id"), nullable=True, index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class TwinSource(Base):
    __tablename__ = "twin_sources"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(160))
    uri: Mapped[str] = mapped_column(String(500))
    version: Mapped[str] = mapped_column(String(80))
    coordinate_reference_system: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="REGISTERED", index=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Connector(Base):
    __tablename__ = "connectors"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    connector_type: Mapped[str] = mapped_column(String(48), index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), default="CONFIGURED", index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class ConnectorSyncRun(Base):
    __tablename__ = "connector_sync_runs"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    connector_id: Mapped[str] = mapped_column(ForeignKey("connectors.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    records_read: Mapped[int] = mapped_column(Integer, default=0)
    records_written: Mapped[int] = mapped_column(Integer, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AIQualityRun(Base):
    __tablename__ = "ai_quality_runs"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    suite: Mapped[str] = mapped_column(String(80), index=True)
    model_provider: Mapped[str] = mapped_column(String(48))
    model_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), index=True)
    score: Mapped[float] = mapped_column(Float)
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    dataset_version: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

# --- V2.0: Full-lifecycle Digital Twin --------------------------------------

class TwinObject(Base):
    """A stable, source-neutral identity for a spatial or functional asset."""
    __tablename__ = "twin_objects"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("twin_objects.id"), nullable=True, index=True)
    object_type: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[dict] = mapped_column(JSON)
    lifecycle_stage: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(48), index=True)
    health_score: Mapped[float] = mapped_column(Float, default=100.0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    geometry_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ifc_guid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    location: Mapped[dict] = mapped_column(JSON, default=dict)
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

class TwinRelation(Base):
    __tablename__ = "twin_relations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("twin_objects.id"), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("twin_objects.id"), index=True)
    relation_type: Mapped[str] = mapped_column(String(40), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

class TwinStateHistory(Base):
    __tablename__ = "twin_state_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    twin_id: Mapped[str] = mapped_column(ForeignKey("twin_objects.id"), index=True)
    previous_status: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(48), index=True)
    source_system: Mapped[str] = mapped_column(String(64))
    evidence_ref: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    effective_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

class TwinEvent(Base):
    __tablename__ = "twin_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    twin_id: Mapped[str] = mapped_column(ForeignKey("twin_objects.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[dict] = mapped_column(JSON)
    domain: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40))
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

class TwinScheduleLink(Base):
    __tablename__ = "twin_schedule_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    twin_id: Mapped[str] = mapped_column(ForeignKey("twin_objects.id"), index=True)
    wbs_code: Mapped[str] = mapped_column(String(64), index=True)
    activity_id: Mapped[str] = mapped_column(String(64), index=True)
    planned_progress: Mapped[float] = mapped_column(Float)
    actual_progress: Mapped[float] = mapped_column(Float)
    schedule_variance_days: Mapped[int] = mapped_column(Integer, default=0)
    cost_code: Mapped[str] = mapped_column(String(64))
    budget: Mapped[float] = mapped_column(Float, default=0.0)
    forecast: Mapped[float] = mapped_column(Float, default=0.0)

class TwinSensor(Base):
    __tablename__ = "twin_sensors"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    twin_id: Mapped[str] = mapped_column(ForeignKey("twin_objects.id"), index=True)
    sensor_type: Mapped[str] = mapped_column(String(40))
    unit: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="ONLINE")
    threshold_warning: Mapped[float] = mapped_column(Float)
    threshold_critical: Mapped[float] = mapped_column(Float)
    latest_value: Mapped[float] = mapped_column(Float)
    sampled_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

class CommissioningItem(Base):
    __tablename__ = "commissioning_items"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    twin_id: Mapped[str] = mapped_column(ForeignKey("twin_objects.id"), index=True)
    system: Mapped[dict] = mapped_column(JSON)
    test_pack: Mapped[str] = mapped_column(String(80))
    stage: Mapped[str] = mapped_column(String(40), index=True)
    punch_open: Mapped[int] = mapped_column(Integer, default=0)
    document_completeness: Mapped[float] = mapped_column(Float, default=0.0)
    readiness: Mapped[float] = mapped_column(Float, default=0.0)

class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    twin_id: Mapped[str] = mapped_column(ForeignKey("twin_objects.id"), index=True)
    work_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), index=True)
    priority: Mapped[str] = mapped_column(String(20))
    description: Mapped[dict] = mapped_column(JSON)
    due_at: Mapped[datetime] = mapped_column(DateTime)

class TwinScenario(Base):
    __tablename__ = "twin_scenarios"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[dict] = mapped_column(JSON)
    scenario_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="READY")
    assumptions: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

# --- V4.0 / Phase 8: operational twin --------------------------------------

class TwinProfile(Base):
    __tablename__ = "twin_profiles"
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    slug: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    center: Mapped[list] = mapped_column(JSON)
    version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default="OPERATIONAL")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class TwinModelVersion(Base):
    __tablename__ = "twin_model_versions"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    version: Mapped[str] = mapped_column(String(80), index=True)
    format: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), index=True)
    checksum: Mapped[str] = mapped_column(String(64))
    uri: Mapped[str] = mapped_column(String(500))
    object_count: Mapped[int] = mapped_column(Integer, default=0)
    change_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class TwinConversionJob(Base):
    __tablename__ = "twin_conversion_jobs"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    input_format: Mapped[str] = mapped_column(String(24))
    input_ref: Mapped[str] = mapped_column(String(500))
    input_checksum: Mapped[str] = mapped_column(String(64))
    output_formats: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    adapter: Mapped[str] = mapped_column(String(80))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TwinTelemetryReading(Base):
    __tablename__ = "twin_telemetry_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    sensor_id: Mapped[str] = mapped_column(ForeignKey("twin_sensors.id"), index=True)
    twin_id: Mapped[str] = mapped_column(ForeignKey("twin_objects.id"), index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    quality: Mapped[str] = mapped_column(String(20), default="GOOD")
    sampled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class TwinCopilotRun(Base):
    __tablename__ = "twin_copilot_runs"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    query: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(48))
    answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="GROUNDED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
