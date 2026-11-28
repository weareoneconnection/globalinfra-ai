"""V2.1 governed execution closure for the first real tool.

Only ``document.generate`` is executable in this release. It creates a
content-addressed owner-response *draft*; it never sends an email or letter.
Execution and verification are deliberately separate operations so approval can
never be mistaken for proof of an outcome.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from collections.abc import Collection
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .twin_sync import sync_case_to_twin
from .models import (
    Action, Approval, Artifact, Case, Evidence, ExecutionReceipt,
    VerificationReceipt, utc_now,
)

DOCUMENT_GENERATE = "document.generate"
DOCUMENT_CONTRACT_VERSION = "document.generate.v1"
V6_POLICY_VERSION = "globalinfra.sod.v6.2"
_EPHEMERAL_AUDIT_KEY = secrets.token_bytes(32)
REQUIRED_OUTPUT_FIELDS = {
    "contract_version", "document_type", "case_id", "action_id", "title",
    "body", "evidence_refs", "delivery_status", "external_delivery_performed",
}


class GovernedExecutionError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _audit_signature(digest: str) -> tuple[str, str]:
    """Sign an audit digest without persisting signing material.

    Production uses the dedicated AUDIT_SIGNING_KEY. Competition role tickets
    and release evidence have separate trust domains. Local/legacy processes
    retain the former fallbacks so existing unsigned demos still start, while
    the production configuration gate requires a stable dedicated key.
    """
    configured = (
        settings.audit_signing_key
        or settings.competition_signing_secret
        or settings.api_key
    )
    key = configured.encode("utf-8") if configured else _EPHEMERAL_AUDIT_KEY
    key_id = (
        settings.audit_signing_key_id
        if settings.audit_signing_key
        else "env:legacy-fallback"
        if configured
        else "ephemeral:process"
    )
    return hmac.new(key, digest.encode("ascii"), hashlib.sha256).hexdigest(), key_id


def _audit_key_for_verification(key_id: str | None) -> bytes | None:
    """Resolve active or retired verification material by immutable key ID."""
    if not key_id:
        return None
    configured = (
        settings.audit_signing_key
        or settings.competition_signing_secret
        or settings.api_key
    )
    active_key_id = (
        settings.audit_signing_key_id
        if settings.audit_signing_key
        else "env:legacy-fallback"
        if configured
        else "ephemeral:process"
    )
    if key_id == active_key_id:
        return configured.encode("utf-8") if configured else _EPHEMERAL_AUDIT_KEY
    try:
        retired = json.loads(settings.audit_verification_keys or "{}")
    except (TypeError, ValueError):
        return None
    secret = retired.get(key_id) if isinstance(retired, dict) else None
    return secret.encode("utf-8") if isinstance(secret, str) and secret else None


def _audit_signature_is_valid(
    digest: str,
    signature: str | None,
    key_id: str | None,
) -> bool:
    key = _audit_key_for_verification(key_id)
    if key is None or not signature:
        return False
    expected = hmac.new(key, digest.encode("ascii"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def _is_v6(action: Action) -> bool:
    return str(action.policy_version or "").startswith("globalinfra.sod.v6")


def action_proposal_digest(db: Session, action: Action) -> str:
    case = db.get(Case, action.case_id)
    evidence = _evidence_payload(
        db, action.case_id, list(action.evidence_refs or [])
    )
    return _digest(
        {
            "case_id": action.case_id,
            "case_snapshot": None
            if case is None
            else {
                "organization_id": case.organization_id,
                "project_id": case.project_id,
                "title": case.title,
                "description": case.description,
                "type": case.type,
                "risk": case.risk,
                "deadline": case.deadline,
                "detected_issues": case.detected_issues,
            },
            "action_id": action.id,
            "action_type": action.action_type,
            "evidence_refs": list(action.evidence_refs or []),
            "evidence_snapshot": evidence,
            "policy": action.policy_version,
        }
    )


def _text(value: dict | None, lang: str) -> str:
    if not value:
        return ""
    return value.get(lang) or value.get("en") or next(iter(value.values()), "")


def approvals_for_action(db: Session, action: Action) -> list[Approval]:
    rows = list(
        db.scalars(
            select(Approval)
            .where(Approval.case_id == action.case_id)
            .order_by(Approval.id)
        )
    )
    return [row for row in rows if row.action_id in {None, action.id}]


def _approval_decision_digest(
    approval: Approval, action: Action | None = None
) -> str:
    return _digest(
        {
            "approval_id": approval.id,
            "case_id": approval.case_id,
            "action_id": approval.action_id,
            "subject": approval.decided_by,
            "role": approval.required_role,
            "decision": approval.status,
            "decided_at": approval.decided_at.isoformat()
            if approval.decided_at
            else None,
            "policy_version": approval.policy_version,
            "proposal_digest": action.proposal_digest if action else None,
        }
    )


def _approval_decision_is_intact(
    approval: Approval, action: Action | None = None
) -> bool:
    if not approval.decision_digest or not approval.decision_signature:
        return False
    digest = _approval_decision_digest(approval, action)
    return hmac.compare_digest(
        approval.decision_digest, digest
    ) and _audit_signature_is_valid(
        digest, approval.decision_signature, approval.decision_key_id
    )


def approval_is_complete(db: Session, action: Action) -> bool:
    approvals = approvals_for_action(db, action)
    if not approvals or not all(row.status == "APPROVED" for row in approvals):
        return False
    if not _is_v6(action):
        return True
    if (
        not action.proposal_digest
        or action.proposal_digest != action_proposal_digest(db, action)
        or any(row.action_id != action.id for row in approvals)
    ):
        return False
    subjects = [row.decided_by for row in approvals]
    roles = {row.required_role for row in approvals}
    if any(not subject for subject in subjects) or len(set(subjects)) != len(subjects):
        return False
    if not all(_approval_decision_is_intact(row, action) for row in approvals):
        return False
    case = db.get(Case, action.case_id)
    if case and case.risk == "CRITICAL":
        return {"project_manager", "hse_manager"}.issubset(roles)
    return "project_manager" in roles


def record_approval_decision(
    db: Session,
    approval: Approval,
    *,
    subject: str,
    roles: Collection[str],
    decision: str,
) -> Action | None:
    """Record an authenticated decision and enforce role/identity separation."""
    action = (
        db.get(Action, approval.action_id)
        if approval.action_id
        else db.scalar(
            select(Action)
            .where(Action.case_id == approval.case_id)
            .order_by(Action.created_at.desc())
        )
    )
    normalized_roles = {str(role) for role in roles}
    if action and _is_v6(action):
        execution_exists = db.scalar(
            select(ExecutionReceipt.id).where(
                ExecutionReceipt.action_id == action.id
            )
        ) is not None
        if action.status != "AWAITING_APPROVAL" or execution_exists:
            raise GovernedExecutionError(
                "ACTION_TERMINAL",
                "Approval decisions are locked once the governed action leaves the approval stage.",
                409,
            )
        if approval.required_role not in normalized_roles:
            raise GovernedExecutionError(
                "REQUIRED_APPROVER_ROLE_MISMATCH",
                f"Approval requires authenticated role {approval.required_role}.",
                403,
            )
        other_subjects = {
            row.decided_by
            for row in approvals_for_action(db, action)
            if row.id != approval.id and row.status == "APPROVED" and row.decided_by
        }
        if subject in other_subjects:
            raise GovernedExecutionError(
                "SEPARATION_OF_DUTIES_REQUIRED",
                "One authenticated subject cannot satisfy multiple required approvals.",
                409,
            )
    approval.status = decision
    approval.decided_by = subject
    approval.decided_role = approval.required_role
    approval.decided_at = utc_now()
    approval.decision_digest = _approval_decision_digest(approval, action)
    approval.decision_signature, approval.decision_key_id = _audit_signature(
        approval.decision_digest
    )
    return action


def _evidence_payload(db: Session, case_id: str, refs: list[str]) -> list[dict]:
    rows = list(db.scalars(select(Evidence).where(Evidence.case_id == case_id)))
    by_ref = {row.source_ref: row for row in rows}
    return [
        {
            "source_ref": ref,
            "title": by_ref[ref].title,
            "excerpt": by_ref[ref].excerpt,
            "confidence": by_ref[ref].confidence,
        }
        for ref in refs
        if ref in by_ref
    ]


def _input_digest(
    case: Case,
    action: Action,
    evidence: list[dict],
    approvals: list[Approval] | None = None,
) -> str:
    return _digest({
        "case_id": case.id,
        "organization_id": case.organization_id,
        "project_id": case.project_id,
        "title": case.title,
        "description": case.description,
        "type": case.type,
        "risk": case.risk,
        "action_id": action.id,
        "action_type": action.action_type,
        "approval_id": action.approval_id,
        "policy_version": action.policy_version,
        "proposal_digest": action.proposal_digest,
        "approval_decisions": [
            {
                "id": row.id,
                "role": row.required_role,
                "subject": row.decided_by,
                "digest": row.decision_digest,
            }
            for row in (approvals or [])
        ],
        "evidence": evidence,
    })


def _draft_output(case: Case, action: Action, evidence: list[dict], composed: dict | None = None) -> dict:
    """Build the draft document. ``composed`` is a validated model-written
    ``{"en", "zh"}`` letter (see ``reply_draft``); without it the fixed
    template is used."""
    refs = [item["source_ref"] for item in evidence]
    refs_en = ", ".join(refs)
    refs_zh = "、".join(refs)
    title_en = f"Response draft — {_text(case.title, 'en')}"
    title_zh = f"回复草案——{_text(case.title, 'zh')}"
    if composed:
        body_en = f"DRAFT — NOT SENT\n\n{composed['en']}\n\nEvidence references: {refs_en}"
        body_zh = f"草案——未发送\n\n{composed['zh']}\n\n证据引用：{refs_zh}"
    else:
        body_en, body_zh = _template_body(case, refs_en, refs_zh)
    return {
        "contract_version": DOCUMENT_CONTRACT_VERSION,
        "document_type": "owner-response-draft",
        "case_id": case.id,
        "action_id": action.id,
        "title": {"en": title_en, "zh": title_zh},
        "body": {"en": body_en, "zh": body_zh},
        "composition": "llm" if composed else "template",
        "evidence_refs": refs,
        "delivery_status": "DRAFT_ONLY_NOT_SENT",
        "external_delivery_performed": False,
    }


def _template_body(case: Case, refs_en: str, refs_zh: str) -> tuple[str, str]:
    body_en = (
        "DRAFT — NOT SENT\n\n"
        f"Subject: Response regarding {_text(case.title, 'en')}\n\n"
        "Dear Sir/Madam,\n\n"
        "We acknowledge the matter described in the Case and are coordinating the "
        "appropriate project review. This governed draft is prepared for internal review "
        "and requires no external delivery in this release.\n\n"
        f"Case description: {_text(case.description, 'en')}\n\n"
        f"Evidence references: {refs_en}\n\n"
        "Regards,\nProject team (draft only)"
    )
    body_zh = (
        "草案——未发送\n\n"
        f"主题：关于{_text(case.title, 'zh')}的回复\n\n"
        "敬启者：\n\n"
        "我们已记录工单中描述的事项，并正在协调适当的项目审查。本受管控草案仅供内部审阅，"
        "本版本不会对外发送。\n\n"
        f"工单描述：{_text(case.description, 'zh')}\n\n"
        f"证据引用：{refs_zh}\n\n"
        "此致\n项目团队（仅为草案）"
    )
    return body_en, body_zh


def _receipt_payload(receipt: ExecutionReceipt, artifact: Artifact | None) -> dict:
    return {
        "id": receipt.id,
        "case_id": receipt.case_id,
        "action_id": receipt.action_id,
        "approval_id": receipt.approval_id,
        "executor": receipt.executor,
        "executor_role": receipt.executor_role,
        "policy_version": receipt.policy_version,
        "action_type": receipt.action_type,
        "started_at": receipt.started_at.isoformat(),
        "completed_at": receipt.completed_at.isoformat() if receipt.completed_at else None,
        "status": receipt.status,
        "evidence_refs": receipt.evidence_refs,
        "input_digest": receipt.input_digest,
        "output_digest": receipt.output_digest,
        "artifact_ref": receipt.artifact_ref,
        "receipt_digest": receipt.receipt_digest,
        "receipt_signature": receipt.receipt_signature,
        "key_id": receipt.key_id,
        "artifact": None if artifact is None else {
            "id": artifact.id,
            "ref": artifact.artifact_ref,
            "type": artifact.artifact_type,
            "media_type": artifact.media_type,
            "digest": artifact.digest,
        },
    }


def _execution_receipt_digest(receipt: ExecutionReceipt) -> str:
    return _digest(
        {
            "id": receipt.id,
            "case_id": receipt.case_id,
            "action_id": receipt.action_id,
            "approval_id": receipt.approval_id,
            "executor": receipt.executor,
            "executor_role": receipt.executor_role,
            "action_type": receipt.action_type,
            "started_at": receipt.started_at.isoformat(),
            "completed_at": receipt.completed_at.isoformat()
            if receipt.completed_at
            else None,
            "status": receipt.status,
            "evidence_refs": receipt.evidence_refs,
            "input_digest": receipt.input_digest,
            "output_digest": receipt.output_digest,
            "artifact_ref": receipt.artifact_ref,
            "policy_version": receipt.policy_version,
        }
    )


def _execution_receipt_is_intact(receipt: ExecutionReceipt) -> bool:
    if not receipt.receipt_digest or not receipt.receipt_signature:
        return False
    digest = _execution_receipt_digest(receipt)
    return hmac.compare_digest(
        receipt.receipt_digest, digest
    ) and _audit_signature_is_valid(
        digest, receipt.receipt_signature, receipt.key_id
    )


def _verification_receipt_digest(receipt: VerificationReceipt) -> str:
    return _digest(
        {
            "id": receipt.id,
            "case_id": receipt.case_id,
            "action_id": receipt.action_id,
            "execution_receipt_id": receipt.execution_receipt_id,
            "approval_id": receipt.approval_id,
            "verified_by": receipt.verified_by,
            "verifier_role": receipt.verifier_role,
            "status": receipt.status,
            "checks": receipt.checks,
            "findings": receipt.findings,
            "evidence_refs": receipt.evidence_refs,
            "artifact_ref": receipt.artifact_ref,
            "artifact_digest": receipt.artifact_digest,
            "policy_version": receipt.policy_version,
            "verified_at": receipt.verified_at.isoformat(),
        }
    )


def _verification_receipt_is_intact(receipt: VerificationReceipt) -> bool:
    if not receipt.verification_digest or not receipt.verification_signature:
        return False
    digest = _verification_receipt_digest(receipt)
    return hmac.compare_digest(
        receipt.verification_digest, digest
    ) and _audit_signature_is_valid(
        digest, receipt.verification_signature, receipt.key_id
    )


def execute_action(
    db: Session,
    action_id: str,
    executor: str = "governed.document.generate",
    composed_body: dict | None = None,
    executor_roles: Collection[str] | None = None,
) -> dict:
    action = db.get(Action, action_id)
    if not action:
        raise GovernedExecutionError("ACTION_NOT_FOUND", "Action not found", 404)
    if action.action_type != DOCUMENT_GENERATE:
        raise GovernedExecutionError("UNSUPPORTED_ACTION_TYPE", "Only document.generate is executable", 422)
    if action.status == "CLOSED":
        raise GovernedExecutionError("ACTION_CLOSED", "Closed actions are terminal and cannot execute again.", 409)

    normalized_roles = {str(role) for role in (executor_roles or [])}
    if _is_v6(action):
        if not normalized_roles.intersection({"engineer", "project_manager"}):
            raise GovernedExecutionError(
                "EXECUTOR_ROLE_REQUIRED",
                "Execution requires an authenticated engineer or project manager role.",
                403,
            )
        approver_subjects = {
            row.decided_by for row in approvals_for_action(db, action) if row.decided_by
        }
        if executor in approver_subjects:
            raise GovernedExecutionError(
                "SEPARATION_OF_DUTIES_REQUIRED",
                "An approver cannot execute the same governed action.",
                409,
            )

    receipt = db.scalar(select(ExecutionReceipt).where(ExecutionReceipt.action_id == action.id))
    if receipt and receipt.status == "SUCCEEDED":
        artifact = db.scalar(select(Artifact).where(Artifact.action_id == action.id))
        if _is_v6(action):
            artifact_digest = _content_digest(artifact.content) if artifact else None
            if (
                not _execution_receipt_is_intact(receipt)
                or not approval_is_complete(db, action)
                or artifact is None
                or not artifact_digest
                or not all(
                    value == artifact_digest
                    for value in (
                        artifact.digest,
                        receipt.output_digest,
                        action.output_digest,
                    )
                )
            ):
                raise GovernedExecutionError(
                    "EXECUTION_RECEIPT_INTEGRITY_FAILED",
                    "Existing execution receipt or artifact failed integrity verification.",
                    409,
                )
        return {
            "status": action.status,
            "idempotent": True,
            "execution_receipt": _receipt_payload(receipt, artifact),
        }

    approval = db.get(Approval, action.approval_id)
    if action.status != "APPROVED" or not approval or approval.status != "APPROVED" or not approval_is_complete(db, action):
        raise GovernedExecutionError(
            "APPROVAL_REQUIRED",
            "Execution blocked: all required human approvals must be APPROVED before execution.",
            409,
        )

    case = db.get(Case, action.case_id)
    if not case:
        raise GovernedExecutionError("CASE_NOT_FOUND", "Case not found for action", 404)
    evidence = _evidence_payload(db, case.id, list(action.evidence_refs or []))
    if not evidence or len(evidence) != len(action.evidence_refs or []):
        action.status = "EXECUTION_FAILED"
        case.status = "EXECUTION_FAILED"
        db.commit()
        raise GovernedExecutionError("EVIDENCE_REQUIRED", "Execution blocked: action evidence references are incomplete.", 422)

    started = utc_now()
    input_digest = _input_digest(
        case, action, evidence, approvals_for_action(db, action)
    )
    action.input_digest = input_digest
    action.status = "EXECUTING"
    case.status = "EXECUTING"
    db.flush()

    try:
        output = _draft_output(case, action, evidence, composed_body)
        content = json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2)
        output_digest = _content_digest(content)
        artifact_id = f"ART-{output_digest.upper()}"
        artifact_ref = f"artifact://sha256/{output_digest}"
        artifact = Artifact(
            id=artifact_id,
            action_id=action.id,
            artifact_ref=artifact_ref,
            artifact_type="owner-response-draft",
            media_type="application/json",
            content=content,
            digest=output_digest,
        )
        db.add(artifact)
        executor_role = next(
            (role for role in ("engineer", "project_manager") if role in normalized_roles),
            None,
        )
        receipt = ExecutionReceipt(
            id=f"EXR-{uuid.uuid4().hex.upper()}",
            case_id=case.id,
            action_id=action.id,
            approval_id=action.approval_id,
            executor=executor,
            executor_role=executor_role,
            policy_version=action.policy_version,
            action_type=action.action_type,
            started_at=started,
            completed_at=utc_now(),
            status="SUCCEEDED",
            evidence_refs=list(action.evidence_refs or []),
            input_digest=input_digest,
            output_digest=output_digest,
            artifact_ref=artifact_ref,
        )
        receipt.receipt_digest = _execution_receipt_digest(receipt)
        receipt.receipt_signature, receipt.key_id = _audit_signature(
            receipt.receipt_digest
        )
        db.add(receipt)
        action.output_digest = output_digest
        action.artifact_ref = artifact_ref
        action.status = "EXECUTED"
        case.status = "EXECUTED"
        db.commit()
        return {
            "status": action.status,
            "idempotent": False,
            "execution_receipt": _receipt_payload(receipt, artifact),
        }
    except GovernedExecutionError:
        raise
    except Exception as exc:
        db.rollback()
        action = db.get(Action, action_id)
        case = db.get(Case, action.case_id) if action else None
        if action:
            action.status = "EXECUTION_FAILED"
        if case:
            case.status = "EXECUTION_FAILED"
        db.commit()
        raise GovernedExecutionError("EXECUTION_FAILED", f"Governed execution failed: {exc}", 500) from exc


def _verification_checks(db: Session, action: Action, receipt: ExecutionReceipt) -> tuple[dict, list[str], Artifact | None, dict | None]:
    approval = db.get(Approval, action.approval_id)
    artifact = db.scalar(select(Artifact).where(Artifact.artifact_ref == receipt.artifact_ref)) if receipt.artifact_ref else None
    checks = {
        "approval_linkage": bool(
            approval and approval.status == "APPROVED" and receipt.approval_id == action.approval_id
            and approval_is_complete(db, action)
        ),
        "execution_receipt": receipt.status == "SUCCEEDED" and receipt.action_id == action.id,
        "execution_receipt_integrity": True,
        "input_integrity": False,
        "actor_separation": True,
        "artifact_exists": artifact is not None,
        "artifact_digest": False,
        "evidence_references": False,
        "required_output_contract": False,
    }
    output = None
    case = db.get(Case, action.case_id)
    current_evidence = _evidence_payload(
        db, action.case_id, list(action.evidence_refs or [])
    )
    checks["input_integrity"] = bool(
        case
        and receipt.input_digest
        == _input_digest(
            case, action, current_evidence, approvals_for_action(db, action)
        )
    )
    if _is_v6(action):
        approvers = {
            row.decided_by for row in approvals_for_action(db, action) if row.decided_by
        }
        checks["actor_separation"] = receipt.executor not in approvers
        checks["execution_receipt_integrity"] = _execution_receipt_is_intact(
            receipt
        )
    if artifact:
        actual_digest = _content_digest(artifact.content)
        digest_values = (artifact.digest, receipt.output_digest, action.output_digest)
        checks["artifact_digest"] = all(digest_values) and all(
            digest == actual_digest for digest in digest_values
        ) and all(
            (
                artifact.action_id == action.id,
                artifact.artifact_ref == receipt.artifact_ref == action.artifact_ref,
                artifact.artifact_ref == f"artifact://sha256/{actual_digest}",
                artifact.id == f"ART-{actual_digest.upper()}",
            )
        )
        try:
            output = json.loads(artifact.content)
        except (TypeError, ValueError):
            output = None
    refs = list(receipt.evidence_refs or [])
    known_refs = set(db.scalars(select(Evidence.source_ref).where(Evidence.case_id == action.case_id)).all())
    checks["evidence_references"] = bool(refs) and set(refs).issubset(known_refs) and output is not None and output.get("evidence_refs") == refs
    checks["required_output_contract"] = bool(
        isinstance(output, dict)
        and REQUIRED_OUTPUT_FIELDS.issubset(output)
        and output.get("contract_version") == DOCUMENT_CONTRACT_VERSION
        and output.get("case_id") == action.case_id
        and output.get("action_id") == action.id
        and output.get("delivery_status") == "DRAFT_ONLY_NOT_SENT"
        and output.get("external_delivery_performed") is False
        and isinstance(output.get("body"), dict)
        and output.get("body", {}).get("en")
        and output.get("body", {}).get("zh")
    )
    findings = [name for name, passed in checks.items() if not passed]
    return checks, findings, artifact, output


def verify_action(
    db: Session,
    action_id: str,
    verifier: str = "independent.verifier",
    verifier_roles: Collection[str] | None = None,
) -> dict:
    action = db.get(Action, action_id)
    if not action:
        raise GovernedExecutionError("ACTION_NOT_FOUND", "Action not found", 404)
    if action.status == "CLOSED":
        raise GovernedExecutionError("ACTION_CLOSED", "Closed actions are terminal and cannot be verified again.", 409)
    if action.status not in {"EXECUTED", "VERIFICATION_FAILED"}:
        raise GovernedExecutionError("EXECUTION_REQUIRED", "Verification requires a successfully executed action.", 409)
    receipt = db.scalar(select(ExecutionReceipt).where(ExecutionReceipt.action_id == action.id))
    if not receipt or receipt.status != "SUCCEEDED":
        raise GovernedExecutionError("EXECUTION_RECEIPT_REQUIRED", "Verification blocked: no successful execution receipt exists.", 409)
    normalized_roles = {str(role) for role in (verifier_roles or [])}
    if _is_v6(action):
        if "verifier" not in normalized_roles:
            raise GovernedExecutionError(
                "VERIFIER_ROLE_REQUIRED",
                "Verification requires an authenticated verifier role.",
                403,
            )
        disallowed_subjects = {
            row.decided_by for row in approvals_for_action(db, action) if row.decided_by
        }
        disallowed_subjects.add(receipt.executor)
        if verifier in disallowed_subjects:
            raise GovernedExecutionError(
                "SEPARATION_OF_DUTIES_REQUIRED",
                "The independent verifier cannot be an approver or executor.",
                409,
            )
    case = db.get(Case, action.case_id)
    action.status = "VERIFYING"
    case.status = "VERIFYING"
    checks, failed_checks, artifact, output = _verification_checks(db, action, receipt)
    if _is_v6(action):
        checks["independent_verifier"] = verifier not in {
            receipt.executor,
            *(
                row.decided_by
                for row in approvals_for_action(db, action)
                if row.decided_by
            ),
        }
        failed_checks = [name for name, passed in checks.items() if not passed]
    passed = not failed_checks
    verification = db.scalar(select(VerificationReceipt).where(VerificationReceipt.action_id == action.id))
    if verification is None:
        verification = VerificationReceipt(
            id=f"VR-{uuid.uuid4().hex.upper()}",
            case_id=action.case_id,
            action_id=action.id,
            execution_receipt_id=receipt.id,
            approval_id=receipt.approval_id,
            verified_by=verifier,
            verifier_role="verifier" if "verifier" in normalized_roles else None,
            policy_version=action.policy_version,
            status="VERIFIED" if passed else "VERIFICATION_FAILED",
            findings=[] if passed else failed_checks,
            checks=checks,
            evidence_refs=list(receipt.evidence_refs or []),
            artifact_ref=receipt.artifact_ref,
            artifact_digest=artifact.digest if artifact else None,
            verified_at=utc_now(),
        )
        db.add(verification)
    else:
        verification.status = "VERIFIED" if passed else "VERIFICATION_FAILED"
        verification.findings = [] if passed else failed_checks
        verification.checks = checks
        verification.evidence_refs = list(receipt.evidence_refs or [])
        verification.artifact_ref = receipt.artifact_ref
        verification.artifact_digest = artifact.digest if artifact else None
        verification.verified_by = verifier
        verification.verifier_role = "verifier" if "verifier" in normalized_roles else None
        verification.policy_version = action.policy_version
        verification.verified_at = utc_now()
    verification.verification_digest = _verification_receipt_digest(verification)
    verification.verification_signature, verification.key_id = _audit_signature(
        verification.verification_digest
    )
    if passed:
        action.status = "VERIFIED"
        case.status = "VERIFIED"
    else:
        action.status = "VERIFICATION_FAILED"
        case.status = "VERIFICATION_FAILED"
    twin_ids = sync_case_to_twin(db, case, verification.status, verification.id)
    db.commit()
    return {
        "status": verification.status,
        "result": "PASS" if passed else "FAIL",
        "verifier": verifier,
        "action_id": action.id,
        "case_id": action.case_id,
        "verification_receipt": {
            "id": verification.id,
            "status": verification.status,
            "checks": verification.checks,
            "findings": verification.findings,
            "artifact_ref": verification.artifact_ref,
            "artifact_digest": verification.artifact_digest,
            "verified_by": verification.verified_by,
            "verifier_role": verification.verifier_role,
            "verification_digest": verification.verification_digest,
            "signature": verification.verification_signature,
            "key_id": verification.key_id,
            "verified_at": verification.verified_at.isoformat(),
        },
        "twin_sync": twin_ids,
    }


def _receipt_chain_is_intact(
    db: Session,
    action: Action,
    execution: ExecutionReceipt | None,
    verification: VerificationReceipt | None,
) -> tuple[bool, Artifact | None]:
    if execution is None or verification is None:
        return False, None
    current_checks, _, artifact, _ = _verification_checks(db, action, execution)
    approvers = {
        row.decided_by
        for row in approvals_for_action(db, action)
        if row.decided_by
    }
    current_checks["independent_verifier"] = verification.verified_by not in {
        execution.executor,
        *approvers,
    }
    failed_checks = [name for name, passed in current_checks.items() if not passed]
    intact = bool(
        execution.status == "SUCCEEDED"
        and execution.case_id == action.case_id
        and execution.action_id == action.id
        and execution.approval_id == action.approval_id
        and execution.action_type == action.action_type
        and execution.policy_version == action.policy_version
        and execution.evidence_refs == list(action.evidence_refs or [])
        and execution.output_digest == action.output_digest
        and execution.artifact_ref == action.artifact_ref
        and verification.status == "VERIFIED"
        and verification.case_id == action.case_id
        and verification.action_id == action.id
        and verification.execution_receipt_id == execution.id
        and verification.approval_id == action.approval_id
        and verification.verifier_role == "verifier"
        and verification.policy_version == action.policy_version
        and verification.evidence_refs == execution.evidence_refs
        and verification.artifact_ref == execution.artifact_ref
        and _execution_receipt_is_intact(execution)
        and _verification_receipt_is_intact(verification)
        and verification.checks == current_checks
        and not failed_checks
        and artifact is not None
        and verification.artifact_digest == artifact.digest
    )
    return intact, artifact


def _closure_digest(
    action: Action,
    execution: ExecutionReceipt,
    verification: VerificationReceipt,
) -> str:
    return _digest(
        {
            "action_id": action.id,
            "case_id": action.case_id,
            "closed_by": action.closed_by,
            "closed_at": action.closed_at.isoformat() if action.closed_at else None,
            "policy_version": action.policy_version,
            "proposal_digest": action.proposal_digest,
            "execution_receipt_digest": execution.receipt_digest,
            "verification_digest": verification.verification_digest,
            "artifact_digest": verification.artifact_digest,
        }
    )


def governed_closure_is_intact(db: Session, action: Action | None) -> bool:
    """Return true only for a complete V6 chain that still verifies now."""
    if action is None or not _is_v6(action) or action.status != "CLOSED":
        return False
    execution = db.scalar(
        select(ExecutionReceipt).where(ExecutionReceipt.action_id == action.id)
    )
    verification = db.scalar(
        select(VerificationReceipt).where(VerificationReceipt.action_id == action.id)
    )
    chain_intact, _ = _receipt_chain_is_intact(
        db, action, execution, verification
    )
    case = db.get(Case, action.case_id)
    if not chain_intact or execution is None or verification is None or case is None:
        return False
    if not action.closure_digest or not action.closure_signature or not action.closed_by:
        return False
    approvers = {
        row.decided_by
        for row in approvals_for_action(db, action)
        if row.decided_by
    }
    if action.closed_by in {execution.executor, verification.verified_by, *approvers}:
        return False
    digest = _closure_digest(action, execution, verification)
    return bool(
        case.status == "CLOSED"
        and approval_is_complete(db, action)
        and hmac.compare_digest(action.closure_digest, digest)
        and _audit_signature_is_valid(
            digest, action.closure_signature, action.closure_key_id
        )
    )


def close_action(
    db: Session,
    action_id: str,
    closer: str = "project.close.controller",
    closer_roles: Collection[str] | None = None,
) -> dict:
    action = db.get(Action, action_id)
    if not action:
        raise GovernedExecutionError("ACTION_NOT_FOUND", "Action not found", 404)
    if action.status != "VERIFIED":
        raise GovernedExecutionError("VERIFICATION_REQUIRED", "Only independently verified actions can be closed.", 409)
    if _is_v6(action):
        roles = {str(role) for role in (closer_roles or [])}
        if "project_manager" not in roles:
            raise GovernedExecutionError(
                "CLOSER_ROLE_REQUIRED",
                "Closure requires an authenticated project manager role.",
                403,
            )
        execution = db.scalar(
            select(ExecutionReceipt).where(ExecutionReceipt.action_id == action.id)
        )
        verification = db.scalar(
            select(VerificationReceipt).where(VerificationReceipt.action_id == action.id)
        )
        receipt_chain_intact, _ = _receipt_chain_is_intact(
            db, action, execution, verification
        )
        if not receipt_chain_intact:
            raise GovernedExecutionError(
                "RECEIPT_CHAIN_INTEGRITY_FAILED",
                "Closure blocked: execution, verification, or artifact integrity failed.",
                409,
            )
        approver_subjects = {
            row.decided_by
            for row in approvals_for_action(db, action)
            if row.decided_by
        }
        if closer in {
            execution.executor if execution else None,
            verification.verified_by if verification else None,
            *approver_subjects,
        }:
            raise GovernedExecutionError(
                "SEPARATION_OF_DUTIES_REQUIRED",
                "The closer cannot be an approver, executor, or independent verifier.",
                409,
            )
    case = db.get(Case, action.case_id)
    action.status = "CLOSED"
    action.closed_by = closer
    action.closed_at = utc_now()
    if _is_v6(action):
        action.closure_digest = _closure_digest(action, execution, verification)
    else:
        action.closure_digest = _digest(
            {
                "action_id": action.id,
                "case_id": action.case_id,
                "closed_by": closer,
                "closed_at": action.closed_at.isoformat(),
                "policy_version": action.policy_version,
            }
        )
    action.closure_signature, action.closure_key_id = _audit_signature(
        action.closure_digest
    )
    case.status = "CLOSED"
    twin_ids = sync_case_to_twin(db, case, "CLOSED", f"CLOSURE-{action.id}")
    db.commit()
    return {
        "twin_sync": twin_ids,
        "status": "CLOSED",
        "action_id": action.id,
        "case_id": case.id,
        "closed_by": action.closed_by,
        "closed_at": action.closed_at.isoformat(),
        "closure_digest": action.closure_digest,
    }


def artifact_payload(artifact: Artifact) -> dict:
    return {
        "id": artifact.id,
        "artifact_ref": artifact.artifact_ref,
        "action_id": artifact.action_id,
        "artifact_type": artifact.artifact_type,
        "media_type": artifact.media_type,
        "content": artifact.content,
        "digest": artifact.digest,
        "created_at": artifact.created_at.isoformat(),
    }
