"""V2.1 governed execution closure for the first real tool.

Only ``document.generate`` is executable in this release. It creates a
content-addressed owner-response *draft*; it never sends an email or letter.
Execution and verification are deliberately separate operations so approval can
never be mistaken for proof of an outcome.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Action, Approval, Artifact, Case, Evidence, ExecutionReceipt,
    VerificationReceipt, utc_now,
)

DOCUMENT_GENERATE = "document.generate"
DOCUMENT_CONTRACT_VERSION = "document.generate.v1"
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


def _text(value: dict | None, lang: str) -> str:
    if not value:
        return ""
    return value.get(lang) or value.get("en") or next(iter(value.values()), "")


def _approval_is_complete(db: Session, action: Action) -> bool:
    approvals = list(db.scalars(select(Approval).where(Approval.case_id == action.case_id)))
    return bool(approvals) and all(approval.status == "APPROVED" for approval in approvals)


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


def _input_digest(case: Case, action: Action, evidence: list[dict]) -> str:
    return _digest({
        "case_id": case.id,
        "title": case.title,
        "description": case.description,
        "type": case.type,
        "risk": case.risk,
        "action_id": action.id,
        "action_type": action.action_type,
        "approval_id": action.approval_id,
        "evidence": evidence,
    })


def _draft_output(case: Case, action: Action, evidence: list[dict]) -> dict:
    refs = [item["source_ref"] for item in evidence]
    refs_en = ", ".join(refs)
    refs_zh = "、".join(refs)
    title_en = f"Owner response draft — {_text(case.title, 'en')}"
    title_zh = f"业主回复草案——{_text(case.title, 'zh')}"
    body_en = (
        "DRAFT — NOT SENT\n\n"
        f"Subject: Response regarding {_text(case.title, 'en')}\n\n"
        "Dear Owner,\n\n"
        "We acknowledge the matter described in the Case and are coordinating the "
        "appropriate project review. This governed draft is prepared for owner review "
        "and requires no external delivery in this release.\n\n"
        f"Case description: {_text(case.description, 'en')}\n\n"
        f"Evidence references: {refs_en}\n\n"
        "Regards,\nProject team (draft only)"
    )
    body_zh = (
        "草案——未发送\n\n"
        f"主题：关于{_text(case.title, 'zh')}的回复\n\n"
        "尊敬的业主：\n\n"
        "我们已记录 Case 中描述的事项，并正在协调适当的项目审查。本受管控草案仅供业主审阅，"
        "本版本不会对外发送。\n\n"
        f"工单描述：{_text(case.description, 'zh')}\n\n"
        f"证据引用：{refs_zh}\n\n"
        "此致\n项目团队（仅为草案）"
    )
    return {
        "contract_version": DOCUMENT_CONTRACT_VERSION,
        "document_type": "owner-response-draft",
        "case_id": case.id,
        "action_id": action.id,
        "title": {"en": title_en, "zh": title_zh},
        "body": {"en": body_en, "zh": body_zh},
        "evidence_refs": refs,
        "delivery_status": "DRAFT_ONLY_NOT_SENT",
        "external_delivery_performed": False,
    }


def _receipt_payload(receipt: ExecutionReceipt, artifact: Artifact | None) -> dict:
    return {
        "id": receipt.id,
        "case_id": receipt.case_id,
        "action_id": receipt.action_id,
        "approval_id": receipt.approval_id,
        "executor": receipt.executor,
        "action_type": receipt.action_type,
        "started_at": receipt.started_at.isoformat(),
        "completed_at": receipt.completed_at.isoformat() if receipt.completed_at else None,
        "status": receipt.status,
        "evidence_refs": receipt.evidence_refs,
        "input_digest": receipt.input_digest,
        "output_digest": receipt.output_digest,
        "artifact_ref": receipt.artifact_ref,
        "artifact": None if artifact is None else {
            "id": artifact.id,
            "ref": artifact.artifact_ref,
            "type": artifact.artifact_type,
            "media_type": artifact.media_type,
            "digest": artifact.digest,
        },
    }


def execute_action(db: Session, action_id: str, executor: str = "governed.document.generate") -> dict:
    action = db.get(Action, action_id)
    if not action:
        raise GovernedExecutionError("ACTION_NOT_FOUND", "Action not found", 404)
    if action.action_type != DOCUMENT_GENERATE:
        raise GovernedExecutionError("UNSUPPORTED_ACTION_TYPE", "Only document.generate is executable", 422)
    if action.status == "CLOSED":
        raise GovernedExecutionError("ACTION_CLOSED", "Closed actions are terminal and cannot execute again.", 409)

    receipt = db.scalar(select(ExecutionReceipt).where(ExecutionReceipt.action_id == action.id))
    if receipt and receipt.status == "SUCCEEDED":
        artifact = db.scalar(select(Artifact).where(Artifact.action_id == action.id))
        return {
            "status": action.status,
            "idempotent": True,
            "execution_receipt": _receipt_payload(receipt, artifact),
        }

    approval = db.get(Approval, action.approval_id)
    if action.status != "APPROVED" or not approval or approval.status != "APPROVED" or not _approval_is_complete(db, action):
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
    input_digest = _input_digest(case, action, evidence)
    action.input_digest = input_digest
    action.status = "EXECUTING"
    case.status = "EXECUTING"
    db.flush()

    try:
        output = _draft_output(case, action, evidence)
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
        receipt = ExecutionReceipt(
            id=f"EXR-{uuid.uuid4().hex.upper()}",
            case_id=case.id,
            action_id=action.id,
            approval_id=action.approval_id,
            executor=executor,
            action_type=action.action_type,
            started_at=started,
            completed_at=utc_now(),
            status="SUCCEEDED",
            evidence_refs=list(action.evidence_refs or []),
            input_digest=input_digest,
            output_digest=output_digest,
            artifact_ref=artifact_ref,
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
            and _approval_is_complete(db, action)
        ),
        "execution_receipt": receipt.status == "SUCCEEDED" and receipt.action_id == action.id,
        "artifact_exists": artifact is not None,
        "artifact_digest": False,
        "evidence_references": False,
        "required_output_contract": False,
    }
    output = None
    if artifact:
        actual_digest = _content_digest(artifact.content)
        checks["artifact_digest"] = all(
            digest == actual_digest
            for digest in (artifact.digest, receipt.output_digest, action.output_digest)
            if digest
        ) and bool(receipt.output_digest)
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


def verify_action(db: Session, action_id: str, verifier: str = "independent.verifier") -> dict:
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
    case = db.get(Case, action.case_id)
    action.status = "VERIFYING"
    case.status = "VERIFYING"
    checks, failed_checks, artifact, output = _verification_checks(db, action, receipt)
    passed = not failed_checks
    verification = db.scalar(select(VerificationReceipt).where(VerificationReceipt.action_id == action.id))
    if verification is None:
        verification = VerificationReceipt(
            id=f"VR-{uuid.uuid4().hex.upper()}",
            case_id=action.case_id,
            action_id=action.id,
            execution_receipt_id=receipt.id,
            approval_id=receipt.approval_id,
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
        verification.verified_at = utc_now()
    if passed:
        action.status = "VERIFIED"
        case.status = "VERIFIED"
    else:
        action.status = "VERIFICATION_FAILED"
        case.status = "VERIFICATION_FAILED"
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
            "verified_at": verification.verified_at.isoformat(),
        },
    }


def close_action(db: Session, action_id: str) -> dict:
    action = db.get(Action, action_id)
    if not action:
        raise GovernedExecutionError("ACTION_NOT_FOUND", "Action not found", 404)
    if action.status != "VERIFIED":
        raise GovernedExecutionError("VERIFICATION_REQUIRED", "Only independently verified actions can be closed.", 409)
    case = db.get(Case, action.case_id)
    action.status = "CLOSED"
    case.status = "CLOSED"
    db.commit()
    return {"status": "CLOSED", "action_id": action.id, "case_id": case.id}


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
