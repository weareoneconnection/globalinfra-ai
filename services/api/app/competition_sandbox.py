"""Isolated, role-ticketed V6 judge sandbox.

The public competition service uses synthetic data only. Every session owns a
new case and short-lived signed role tickets. The tickets deliberately model
separate people so a judge can verify the same separation-of-duties policy
used by authenticated pilot deployments without receiving reusable pilot
credentials.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .competition import GOLDEN_INPUT
from .config import settings
from .database import get_db
from .governed_execution import (
    GovernedExecutionError,
    _audit_signature_is_valid,
    _execution_receipt_digest,
    action_proposal_digest,
    close_action,
    execute_action,
    governed_closure_is_intact,
    record_approval_decision,
    verify_action,
)
from .i18n import bi
from .intake import build_intake_result
from .models import (
    Action,
    Approval,
    Artifact,
    Case,
    CompetitionSession,
    Evidence,
    ExecutionReceipt,
    Project,
    TwinObject,
    VerificationReceipt,
    utc_now,
)
from .workflow import analyze_case


router = APIRouter(prefix="/competition/sessions", tags=["competition-v6-sandbox"])
POLICY_VERSION = "globalinfra.sod.v6.2"
SANDBOX_ORGANIZATION_ID = "globalinfra-competition-sandbox"
SANDBOX_PROJECT_CODE = "COMP-SYNTH-MY-P47"
SANDBOX_TWIN_ID = "TWIN-COMP-MYRAIL-V12-P47"
_EPHEMERAL_TICKET_SECRET = secrets.token_bytes(32)
_ROLE_SPECS = {
    "project_manager": {
        "roles": ["project_manager", "approver"],
        "label": "Project Manager",
    },
    "hse_manager": {
        "roles": ["hse_manager", "approver"],
        "label": "HSE Manager",
    },
    "engineer": {"roles": ["engineer"], "label": "Document Controller"},
    "verifier": {"roles": ["verifier"], "label": "Independent Verifier"},
    "closer": {"roles": ["project_manager"], "label": "Case Close Controller"},
}


@dataclass(frozen=True)
class SandboxActor:
    subject: str
    role_key: str
    roles: frozenset[str]


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _ticket_secret() -> bytes:
    configured = settings.competition_signing_secret or settings.api_key
    return configured.encode("utf-8") if configured else _EPHEMERAL_TICKET_SECRET


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _issue_ticket(session_id: str, role_key: str, expires_at: datetime) -> dict:
    spec = _ROLE_SPECS[role_key]
    subject = f"judge:{session_id}:{role_key}"
    payload = {
        "v": 1,
        "sid": session_id,
        "sub": subject,
        "role_key": role_key,
        "roles": spec["roles"],
        "exp": int(expires_at.replace(tzinfo=UTC).timestamp()),
        "nonce": secrets.token_urlsafe(8),
    }
    encoded = _b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _b64encode(
        hmac.new(_ticket_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    return {
        "ticket": f"{encoded}.{signature}",
        "subject": subject,
        "role": role_key,
        "label": spec["label"],
        "expires_at": expires_at.isoformat(),
    }


def _verify_ticket(ticket: str, session_id: str) -> SandboxActor:
    try:
        encoded, supplied_signature = ticket.split(".", 1)
        expected_signature = _b64encode(
            hmac.new(_ticket_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError("signature")
        payload = json.loads(_b64decode(encoded))
        if payload.get("sid") != session_id:
            raise ValueError("session")
        if int(payload.get("exp", 0)) <= int(datetime.now(UTC).timestamp()):
            raise ValueError("expired")
        role_key = str(payload["role_key"])
        if role_key not in _ROLE_SPECS:
            raise ValueError("role")
        roles = frozenset(str(value) for value in payload.get("roles", []))
        if roles != frozenset(_ROLE_SPECS[role_key]["roles"]):
            raise ValueError("scope")
        return SandboxActor(
            subject=str(payload["sub"]), role_key=role_key, roles=roles
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            401,
            detail={
                "code": "INVALID_ROLE_TICKET",
                "message": "The competition role ticket is invalid or expired.",
            },
        ) from None


def _ensure_enabled() -> None:
    if not settings.competition_v6_enabled or not settings.sandbox_mode:
        raise HTTPException(404, "Competition V6 sandbox is not enabled")


def _session(db: Session, session_id: str) -> CompetitionSession:
    _ensure_enabled()
    row = db.get(CompetitionSession, session_id)
    if row is None:
        raise HTTPException(404, "Competition session not found")
    if row.expires_at <= utc_now():
        row.status = "EXPIRED"
        db.commit()
        raise HTTPException(
            410,
            detail={
                "code": "SESSION_EXPIRED",
                "message": "This judge session expired. Create or reset the session.",
            },
        )
    if row.status in {"RESET", "EXPIRED"}:
        raise HTTPException(410, "Competition session is no longer active")
    return row


def _actor(
    db: Session,
    session_id: str,
    ticket: str,
    allowed_role_keys: set[str] | None = None,
) -> tuple[CompetitionSession, SandboxActor]:
    session = _session(db, session_id)
    actor = _verify_ticket(ticket, session_id)
    if allowed_role_keys is not None and actor.role_key not in allowed_role_keys:
        raise HTTPException(
            403,
            detail={
                "code": "ROLE_SCOPE_REQUIRED",
                "message": f"This step requires one of {sorted(allowed_role_keys)}.",
            },
        )
    return session, actor


def _assert_session_mutable(row: CompetitionSession) -> None:
    if row.status == "CLOSED":
        raise HTTPException(
            409,
            detail={
                "code": "ACTION_TERMINAL",
                "message": "Closed competition sessions are immutable; reset to start a fresh session.",
            },
        )


def _session_tickets(row: CompetitionSession) -> dict:
    return {
        role_key: _issue_ticket(row.id, role_key, row.expires_at)
        for role_key in _ROLE_SPECS
    }


def _sandbox_project(db: Session) -> Project:
    """Return a synthetic-only project that never aliases a tenant project."""
    project = db.scalar(
        select(Project).where(
            Project.code == SANDBOX_PROJECT_CODE,
            Project.organization_id == SANDBOX_ORGANIZATION_ID,
        )
    )
    if project is None:
        project = Project(
            organization_id=SANDBOX_ORGANIZATION_ID,
            code=SANDBOX_PROJECT_CODE,
            name=bi("Competition synthetic Malaysia rail", "参赛合成马来西亚轨道项目"),
            country_code="MY",
            country_name=bi("Malaysia", "马来西亚"),
            domain=bi("Synthetic rail sandbox", "合成轨道沙箱"),
            region="COMPETITION_SANDBOX",
            status="SYNTHETIC_DEMO",
            risk_level="CRITICAL",
            languages=["English", "Bahasa Melayu", "中文"],
        )
        db.add(project)
        db.flush()
    twin = db.get(TwinObject, SANDBOX_TWIN_ID)
    if twin is None:
        db.add(
            TwinObject(
                id=SANDBOX_TWIN_ID,
                project_id=project.id,
                object_type="PIER",
                name=bi("Synthetic viaduct V-12 pier P47", "合成 V-12 高架桥 P47 桥墩"),
                lifecycle_stage="CONSTRUCTION",
                status="SYNTHETIC_HSE_HOLD",
                health_score=72.0,
                progress=64.0,
                geometry_ref="synthetic://competition/P47",
                location={"country": "MY", "precision": "SCENARIO_ONLY"},
                properties={"provenance": "SYNTHETIC_COMPETITION_ONLY"},
            )
        )
        db.flush()
    elif twin.project_id != project.id:
        raise HTTPException(503, "Competition sandbox Twin ID ownership is invalid")
    return project


def _new_session(db: Session, reset_count: int = 0) -> CompetitionSession:
    project = _sandbox_project(db)
    session_id = f"CS-{uuid.uuid4().hex[:20].upper()}"
    case_id = f"CASE-COMP-{uuid.uuid4().hex[:16].upper()}"
    intake = build_intake_result(GOLDEN_INPUT)
    now = utc_now()
    expires_at = now + timedelta(minutes=settings.competition_session_ttl_minutes)
    snapshot_digest = _digest(
        {
            "input": GOLDEN_INPUT,
            "project": project.code,
            "policy": POLICY_VERSION,
            "synthetic": True,
        }
    )
    case = Case(
        id=case_id,
        organization_id=SANDBOX_ORGANIZATION_ID,
        project_id=project.id,
        title=bi(
            "Malaysia Pier P47 working-at-height owner notice",
            "马来西亚 P47 桥墩高处作业业主通知",
        ),
        description=bi(
            GOLDEN_INPUT,
            "P47 桥墩存在无防护临边，应立即停止高处作业，并在 24 小时内"
            "提交防坠措施、作业许可证及胜任人员记录。",
        ),
        type=intake["case_type_label"],
        risk=intake["risk"],
        status="NEW",
        deadline=intake["deadline"] or bi("Within 24 hours", "24 小时内"),
        source_language=bi("English / Chinese", "英文 / 中文"),
        detected_issues=intake["issues"],
        project_routing_confidence=0.98,
        routing_status="ROUTED",
    )
    row = CompetitionSession(
        id=session_id,
        case_id=case_id,
        organization_id=SANDBOX_ORGANIZATION_ID,
        status="READY",
        created_at=now,
        expires_at=expires_at,
        reset_count=reset_count,
        snapshot_digest=snapshot_digest,
    )
    db.add(case)
    db.add(row)
    db.commit()
    return row


def _state(db: Session, row: CompetitionSession) -> dict:
    case = db.get(Case, row.case_id)
    action = db.scalar(
        select(Action)
        .where(Action.case_id == row.case_id)
        .order_by(Action.created_at.desc())
    )
    approvals = list(
        db.scalars(
            select(Approval)
            .where(Approval.case_id == row.case_id)
            .order_by(Approval.id)
        )
    )
    evidence = list(
        db.scalars(
            select(Evidence)
            .where(Evidence.case_id == row.case_id)
            .order_by(Evidence.confidence.desc(), Evidence.id)
        )
    )
    execution = (
        db.scalar(
            select(ExecutionReceipt).where(ExecutionReceipt.action_id == action.id)
        )
        if action
        else None
    )
    verification = (
        db.scalar(
            select(VerificationReceipt).where(
                VerificationReceipt.action_id == action.id
            )
        )
        if action
        else None
    )
    artifact = (
        db.scalar(select(Artifact).where(Artifact.action_id == action.id))
        if action
        else None
    )
    approved_roles = {
        item.required_role for item in approvals if item.status == "APPROVED"
    }
    next_steps: list[str] = []
    if action is None:
        next_steps = ["analyze"]
    elif action.status == "AWAITING_APPROVAL":
        if "project_manager" not in approved_roles:
            next_steps.append("project_manager_approve")
        if "hse_manager" not in approved_roles:
            next_steps.append("hse_manager_approve")
    elif action.status == "APPROVED":
        next_steps = ["execute"]
    elif action.status in {"EXECUTED", "VERIFICATION_FAILED"}:
        next_steps = ["verify"]
    elif action.status == "VERIFIED":
        next_steps = ["close"]
    return {
        "session": {
            "id": row.id,
            "case_id": row.case_id,
            "status": row.status,
            "created_at": row.created_at.isoformat(),
            "expires_at": row.expires_at.isoformat(),
            "reset_count": row.reset_count,
            "snapshot_digest": row.snapshot_digest,
            "synthetic": True,
            "shared_history": False,
        },
        "case": None
        if case is None
        else {
            "id": case.id,
            "status": case.status,
            "title": case.title,
            "description": case.description,
            "risk": case.risk,
            "deadline": case.deadline,
            "project_id": case.project_id,
            "twin_id": SANDBOX_TWIN_ID,
        },
        "approvals": [
            {
                "id": item.id,
                "required_role": item.required_role,
                "status": item.status,
                "decided_by": item.decided_by,
                "decided_at": item.decided_at.isoformat()
                if item.decided_at
                else None,
                "decision_digest": item.decision_digest,
                "decision_signature": item.decision_signature,
                "key_id": item.decision_key_id,
            }
            for item in approvals
        ],
        "evidence": [
            {
                "id": item.id,
                "source_ref": item.source_ref,
                "title": item.title,
                "confidence": item.confidence,
                "verified": item.verified,
            }
            for item in evidence
        ],
        "action": None
        if action is None
        else {
            "id": action.id,
            "status": action.status,
            "type": action.action_type,
            "policy_version": action.policy_version,
            "proposal_digest": action.proposal_digest,
            "closed_by": action.closed_by,
            "closed_at": action.closed_at.isoformat() if action.closed_at else None,
            "closure_digest": action.closure_digest,
            "closure_signature": action.closure_signature,
            "closure_key_id": action.closure_key_id,
        },
        "receipts": {
            "execution": None
            if execution is None
            else {
                "id": execution.id,
                "status": execution.status,
                "executor": execution.executor,
                "executor_role": execution.executor_role,
                "output_digest": execution.output_digest,
                "receipt_digest": execution.receipt_digest,
                "signature": execution.receipt_signature,
                "key_id": execution.key_id,
            },
            "verification": None
            if verification is None
            else {
                "id": verification.id,
                "status": verification.status,
                "verified_by": verification.verified_by,
                "verifier_role": verification.verifier_role,
                "checks": verification.checks,
                "verification_digest": verification.verification_digest,
                "signature": verification.verification_signature,
                "key_id": verification.key_id,
            },
            "artifact": None
            if artifact is None
            else {
                "id": artifact.id,
                "digest": artifact.digest,
                "delivery_status": "DRAFT_ONLY_NOT_SENT",
            },
        },
        "next_steps": next_steps,
        "complete": governed_closure_is_intact(db, action),
        "governance": {
            "policy_version": POLICY_VERSION,
            "separation_of_duties": True,
            "external_delivery_performed": False,
            "data_boundary": "SYNTHETIC_COMPETITION_ONLY",
        },
    }


def _error(exc: GovernedExecutionError) -> HTTPException:
    return HTTPException(
        exc.status_code, detail={"code": exc.code, "message": exc.message}
    )


def _tampered_execution_receipt_copy(receipt: ExecutionReceipt) -> SimpleNamespace:
    """Return an untracked receipt copy with one signed field changed.

    Jury Mode uses this copy to demonstrate that a signed receipt rejects a
    one-field modification.  It deliberately does not mutate the SQLAlchemy
    entity or accept arbitrary client input, so the canonical evidence chain
    remains read-only throughout the probe.
    """
    return SimpleNamespace(
        id=receipt.id,
        case_id=receipt.case_id,
        action_id=receipt.action_id,
        approval_id=receipt.approval_id,
        executor=f"{receipt.executor}:tampered-copy",
        executor_role=receipt.executor_role,
        action_type=receipt.action_type,
        started_at=receipt.started_at,
        completed_at=receipt.completed_at,
        status=receipt.status,
        evidence_refs=list(receipt.evidence_refs or []),
        input_digest=receipt.input_digest,
        output_digest=receipt.output_digest,
        artifact_ref=receipt.artifact_ref,
        policy_version=receipt.policy_version,
    )


@router.post("", status_code=201)
def create_session(db: Session = Depends(get_db)):
    _ensure_enabled()
    row = _new_session(db)
    return {
        "session": _state(db, row)["session"],
        "role_tickets": _session_tickets(row),
        "state": _state(db, row),
    }


@router.get("/{session_id}/state")
def session_state(
    session_id: str,
    role_ticket: str = Header(alias="X-Competition-Role-Ticket"),
    db: Session = Depends(get_db),
):
    row, _ = _actor(db, session_id, role_ticket)
    return _state(db, row)


@router.post("/{session_id}/reset", status_code=201)
def reset_session(
    session_id: str,
    role_ticket: str = Header(alias="X-Competition-Role-Ticket"),
    db: Session = Depends(get_db),
):
    old, _ = _actor(db, session_id, role_ticket)
    old.status = "RESET"
    next_reset_count = old.reset_count + 1
    db.commit()
    row = _new_session(db, reset_count=next_reset_count)
    return {
        "replaces_session_id": old.id,
        "session": _state(db, row)["session"],
        "role_tickets": _session_tickets(row),
        "state": _state(db, row),
    }


@router.post("/{session_id}/analyze")
async def analyze_session(
    session_id: str,
    role_ticket: str = Header(alias="X-Competition-Role-Ticket"),
    db: Session = Depends(get_db),
):
    row, _ = _actor(db, session_id, role_ticket, {"project_manager"})
    _assert_session_mutable(row)
    existing = db.scalar(select(Action).where(Action.case_id == row.case_id))
    if existing is not None:
        existing_receipt = db.scalar(
            select(ExecutionReceipt).where(
                ExecutionReceipt.action_id == existing.id
            )
        )
        existing_approvals = list(
            db.scalars(
                select(Approval).where(Approval.case_id == row.case_id)
            )
        )
        if (
            existing_receipt is not None
            or existing.status != "AWAITING_APPROVAL"
            or any(item.status != "PENDING" for item in existing_approvals)
        ):
            raise HTTPException(
                409,
                detail={
                    "code": "ACTION_TERMINAL",
                    "message": "Analysis is locked after the first approval or execution.",
                },
            )
        return _state(db, row)
    if existing is None:
        await analyze_case(
            db,
            row.case_id,
            model_route="mock",
            data_classification="public",
        )
    action = db.scalar(
        select(Action)
        .where(Action.case_id == row.case_id)
        .order_by(Action.created_at.desc())
    )
    approvals = list(
        db.scalars(
            select(Approval)
            .where(Approval.case_id == row.case_id)
            .order_by(Approval.id)
        )
    )
    if action is None or len(approvals) < 2:
        raise HTTPException(
            409,
            detail={
                "code": "TWO_PERSON_APPROVALS_REQUIRED",
                "message": "The critical HSE case must create PM and HSE approvals.",
            },
        )
    for index, approval in enumerate(approvals):
        approval.sandbox_session_id = row.id
        approval.required_role = "project_manager" if index == 0 else "hse_manager"
        approval.policy_version = POLICY_VERSION
    action.policy_version = POLICY_VERSION
    action.proposed_by = "competition:v6:analysis"
    action.proposal_digest = action_proposal_digest(db, action)
    row.status = "AWAITING_APPROVAL"
    db.commit()
    return _state(db, row)


@router.post("/{session_id}/approvals/{approval_id}/approve")
def approve_session_action(
    session_id: str,
    approval_id: int,
    role_ticket: str = Header(alias="X-Competition-Role-Ticket"),
    db: Session = Depends(get_db),
):
    row, actor = _actor(
        db, session_id, role_ticket, {"project_manager", "hse_manager"}
    )
    _assert_session_mutable(row)
    approval = db.get(Approval, approval_id)
    if (
        approval is None
        or approval.case_id != row.case_id
        or approval.sandbox_session_id != row.id
    ):
        raise HTTPException(404, "Session approval not found")
    if approval.required_role != actor.role_key:
        raise HTTPException(
            403,
            detail={
                "code": "REQUIRED_APPROVER_ROLE_MISMATCH",
                "message": f"Approval requires {approval.required_role}.",
            },
        )
    other_actors = set(
        db.scalars(
            select(Approval.decided_by).where(
                Approval.case_id == row.case_id,
                Approval.status == "APPROVED",
                Approval.id != approval.id,
            )
        )
    )
    if actor.subject in other_actors:
        raise HTTPException(
            409,
            detail={
                "code": "SEPARATION_OF_DUTIES_REQUIRED",
                "message": "One subject cannot satisfy both required approvals.",
            },
        )
    try:
        record_approval_decision(
            db,
            approval,
            subject=actor.subject,
            roles=actor.roles,
            decision="APPROVED",
        )
    except GovernedExecutionError as exc:
        raise _error(exc) from exc
    action = db.get(Action, approval.action_id)
    all_approvals = list(
        db.scalars(select(Approval).where(Approval.case_id == row.case_id))
    )
    if action and all(item.status == "APPROVED" for item in all_approvals):
        if len({item.decided_by for item in all_approvals}) != len(all_approvals):
            raise HTTPException(409, "Required approvals must use distinct subjects")
        action.status = "APPROVED"
        action.approved_at = utc_now()
        case = db.get(Case, row.case_id)
        case.status = "APPROVED"
        row.status = "APPROVED"
    db.commit()
    return _state(db, row)


@router.post("/{session_id}/execute")
def execute_session_action(
    session_id: str,
    role_ticket: str = Header(alias="X-Competition-Role-Ticket"),
    db: Session = Depends(get_db),
):
    row, actor = _actor(db, session_id, role_ticket, {"engineer"})
    _assert_session_mutable(row)
    action = db.scalar(
        select(Action)
        .where(Action.case_id == row.case_id)
        .order_by(Action.created_at.desc())
    )
    if action is None:
        raise HTTPException(409, "Analyze the session before execution")
    try:
        result = execute_action(
            db,
            action.id,
            actor.subject,
            None,
            executor_roles=actor.roles,
        )
    except GovernedExecutionError as exc:
        raise _error(exc) from exc
    row.status = result["status"]
    db.commit()
    return _state(db, row)


@router.post("/{session_id}/verify")
def verify_session_action(
    session_id: str,
    role_ticket: str = Header(alias="X-Competition-Role-Ticket"),
    db: Session = Depends(get_db),
):
    row, actor = _actor(db, session_id, role_ticket, {"verifier"})
    _assert_session_mutable(row)
    action = db.scalar(
        select(Action)
        .where(Action.case_id == row.case_id)
        .order_by(Action.created_at.desc())
    )
    if action is None:
        raise HTTPException(409, "Analyze and execute the session before verification")
    try:
        result = verify_action(
            db,
            action.id,
            actor.subject,
            verifier_roles=actor.roles,
        )
    except GovernedExecutionError as exc:
        raise _error(exc) from exc
    row.status = result["status"]
    db.commit()
    return _state(db, row)


@router.post("/{session_id}/close")
def close_session_action(
    session_id: str,
    role_ticket: str = Header(alias="X-Competition-Role-Ticket"),
    db: Session = Depends(get_db),
):
    row, actor = _actor(db, session_id, role_ticket, {"closer"})
    _assert_session_mutable(row)
    action = db.scalar(
        select(Action)
        .where(Action.case_id == row.case_id)
        .order_by(Action.created_at.desc())
    )
    if action is None:
        raise HTTPException(409, "Analyze the session before closure")
    try:
        close_action(
            db,
            action.id,
            actor.subject,
            closer_roles=actor.roles,
        )
    except GovernedExecutionError as exc:
        raise _error(exc) from exc
    row.status = "CLOSED"
    db.commit()
    return _state(db, row)


@router.post("/{session_id}/tamper-probe")
def probe_tampered_receipt_copy(
    session_id: str,
    role_ticket: str = Header(alias="X-Competition-Role-Ticket"),
    db: Session = Depends(get_db),
):
    """Reject an in-memory receipt modification without touching evidence.

    The probe is available only to the session's dedicated closer after the
    governed workflow is fully closed.  It changes the signed ``executor``
    field on an untracked copy, verifies that the original signature no longer
    validates, then reloads the canonical state and proves its digest and
    closure chain are unchanged.
    """
    row, actor = _actor(db, session_id, role_ticket, {"closer"})
    action = db.scalar(
        select(Action)
        .where(Action.case_id == row.case_id)
        .order_by(Action.created_at.desc())
    )
    execution = (
        db.scalar(
            select(ExecutionReceipt).where(
                ExecutionReceipt.action_id == action.id
            )
        )
        if action
        else None
    )
    if (
        row.status != "CLOSED"
        or action is None
        or action.status != "CLOSED"
        or execution is None
        or not governed_closure_is_intact(db, action)
    ):
        raise HTTPException(
            409,
            detail={
                "code": "JURY_EVIDENCE_INCOMPLETE",
                "message": "Complete and close the governed session before running the tamper probe.",
            },
        )
    if action.closed_by != actor.subject:
        raise HTTPException(
            409,
            detail={
                "code": "CLOSER_IDENTITY_MISMATCH",
                "message": "Only the subject that closed this session can run its tamper probe.",
            },
        )

    canonical_digest = _execution_receipt_digest(execution)
    canonical_signature_valid = (
        bool(execution.receipt_digest)
        and hmac.compare_digest(execution.receipt_digest, canonical_digest)
        and _audit_signature_is_valid(
            canonical_digest, execution.receipt_signature, execution.key_id
        )
    )
    if not canonical_signature_valid:
        raise HTTPException(
            409,
            detail={
                "code": "CANONICAL_EVIDENCE_INVALID",
                "message": "The canonical execution receipt is not valid; no tamper demonstration was run.",
            },
        )

    canonical_state_digest = _digest(_state(db, row))
    tampered_copy = _tampered_execution_receipt_copy(execution)
    tampered_digest = _execution_receipt_digest(tampered_copy)
    tampered_signature_valid = _audit_signature_is_valid(
        tampered_digest, execution.receipt_signature, execution.key_id
    )

    # Expire the identity map and read the records again.  This makes the API
    # response prove the database-backed evidence is unchanged, rather than
    # merely comparing two references to the same in-memory object.
    db.expire_all()
    canonical_row = db.get(CompetitionSession, session_id)
    canonical_action = (
        db.scalar(
            select(Action)
            .where(Action.case_id == canonical_row.case_id)
            .order_by(Action.created_at.desc())
        )
        if canonical_row
        else None
    )
    canonical_state_unchanged = bool(
        canonical_row
        and canonical_action
        and governed_closure_is_intact(db, canonical_action)
        and hmac.compare_digest(
            canonical_state_digest, _digest(_state(db, canonical_row))
        )
    )
    if tampered_signature_valid or not canonical_state_unchanged:
        raise HTTPException(
            500,
            detail={
                "code": "TAMPER_PROBE_INVARIANT_FAILED",
                "message": "The tamper probe did not preserve its fail-closed invariants.",
            },
        )

    return {
        "schema": "globalinfra.jury-tamper-probe.v1",
        "session_id": session_id,
        "probe": {
            "status": "INVALID_SIGNATURE",
            "reason": "SIGNED_FIELD_TAMPERED",
            "field": "execution.executor",
            "canonical_digest": canonical_digest,
            "tampered_digest": tampered_digest,
            "signature_valid": False,
        },
        "canonical": {
            "status": "VERIFIED_INTACT",
            "state_digest": canonical_state_digest,
            "signature_valid": True,
            "unchanged": True,
            "complete": True,
            "closed_by": actor.subject,
            "external_delivery_performed": False,
        },
    }
