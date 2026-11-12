import json
from pathlib import Path

import pytest
import app.competition as competition_module
from app.competition import GOLDEN_CASE_ID, release_validation_checks
from app.competition_sandbox import (
    SANDBOX_ORGANIZATION_ID,
    SANDBOX_TWIN_ID,
)
from app.database import SessionLocal
from app.evaluation_artifacts import (
    SUITE_SPECS,
    build_release_payload,
    sign_release_payload,
    write_release_evidence,
)
from app.governed_execution import GovernedExecutionError, close_action
from app.models import (
    Action,
    Artifact,
    Case,
    Evidence,
    ExecutionReceipt,
    KnowledgeDocument,
    Project,
    VerificationReceipt,
)
from sqlalchemy import select


def _header(ticket: str) -> dict[str, str]:
    return {"X-Competition-Role-Ticket": ticket}


def _new_session(client) -> dict:
    response = client.post("/competition/sessions")
    assert response.status_code == 201, response.text
    return response.json()


def _verified_session(client) -> tuple[dict, str]:
    """Create one isolated V6 session with a valid signed receipt chain."""
    created = _new_session(client)
    session_id = created["session"]["id"]
    tickets = created["role_tickets"]
    analyzed = client.post(
        f"/competition/sessions/{session_id}/analyze",
        headers=_header(tickets["project_manager"]["ticket"]),
    )
    assert analyzed.status_code == 200, analyzed.text
    approvals = {
        row["required_role"]: row for row in analyzed.json()["approvals"]
    }
    for role in ("project_manager", "hse_manager"):
        response = client.post(
            f"/competition/sessions/{session_id}/approvals/{approvals[role]['id']}/approve",
            headers=_header(tickets[role]["ticket"]),
        )
        assert response.status_code == 200, response.text
    executed = client.post(
        f"/competition/sessions/{session_id}/execute",
        headers=_header(tickets["engineer"]["ticket"]),
    )
    assert executed.status_code == 200, executed.text
    action_id = executed.json()["action"]["id"]
    verified = client.post(
        f"/competition/sessions/{session_id}/verify",
        headers=_header(tickets["verifier"]["ticket"]),
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["receipts"]["verification"]["status"] == "VERIFIED"
    return created, action_id


def _release_artifact(
    tmp_path,
    *,
    key: str,
    failed_suite: str | None = None,
    failed_validation: str | None = None,
):
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    for spec in SUITE_SPECS:
        dataset = competition_module.REPO_ROOT / spec["dataset"]
        count = sum(1 for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip())
        (raw / spec["output"]).write_text(
            json.dumps({
                "suite": spec["id"],
                "status": "FAILED" if spec["id"] == failed_suite else "PASSED",
                "total_cases": count,
                "metrics": {"test_metric": 1.0},
                "gates": {"test_gate": spec["id"] != failed_suite},
            }),
            encoding="utf-8",
        )
    payload = build_release_payload(
        raw_dir=raw,
        repo_root=competition_module.REPO_ROOT,
        git_info={"commit": "test-deploy-commit", "dirty": False, "tracked_changes": []},
    )
    payload["validation"] = {
        "api_tests": {
            "status": "FAILED" if failed_validation == "api_tests" else "PASSED",
            "tests": 283,
            "passed": 282 if failed_validation == "api_tests" else 283,
            "failures": 1 if failed_validation == "api_tests" else 0,
            "errors": 0,
            "skipped": 0,
        },
        "web_build": "FAILED" if failed_validation == "web_build" else "PASSED",
        "migration_check": (
            "FAILED" if failed_validation == "migration_check" else "PASSED"
        ),
        "full_stack_smoke": (
            "FAILED" if failed_validation == "full_stack_smoke" else "PASSED"
        ),
    }
    envelope = sign_release_payload(
        payload,
        hmac_key=key,
        key_id="test-release:v1",
    )
    path = tmp_path / "release-evidence.json"
    write_release_evidence(path, envelope)
    return path, envelope


def test_competition_evaluation_is_reproducible_and_passes(client):
    response = client.get("/competition/evaluation?include_cases=true")
    assert response.status_code == 200
    body = response.json()
    assert body["suite"] == "AI_OUTBOUND_COMPETITION_EVIDENCE"
    assert body["total_cases"] == 30
    assert body["status"] == "PASSED"
    assert len(body["cases"]) == 30
    assert body["category_coverage"] == {
        "multilingual_event": 8,
        "regulation_permit": 8,
        "contract_claim": 6,
        "local_hse_training": 4,
        "twin_operation": 4,
    }
    assert all(body["gates"].values())


def test_release_gate_rejects_empty_or_partially_passing_test_attestation():
    base = {
        "web_build": "PASSED", "migration_check": "PASSED",
        "full_stack_smoke": "PASSED",
    }
    for api_tests in (
        {"status": "PASSED", "tests": 0, "passed": 0},
        {"status": "PASSED", "tests": 314, "passed": 313},
        {"status": "PASSED", "tests": 314, "passed": 314, "errors": 1},
        {
            "status": "PASSED", "tests": "314", "passed": "314",
            "failures": "invalid", "errors": 0, "skipped": 0,
        },
    ):
        checks = release_validation_checks({"validation": {**base, "api_tests": api_tests}})
        assert checks["api_tests"] is False


def test_public_competition_evaluation_ignores_tenant_documents(client):
    with SessionLocal() as db:
        document = KnowledgeDocument(
            title={"en": "Malaysia occupational safety Act 514 secret", "zh": "保密"},
            category={"en": "Customer", "zh": "客户"},
            jurisdiction={"en": "Project", "zh": "项目"},
            language={"en": "English", "zh": "英语"},
            source_ref="CUSTOMER-SECRET-MUST-NOT-LEAK",
            content={"en": "DOSH competent person working at height", "zh": "保密"},
            summary={"en": "private customer record", "zh": "保密"},
            project_id=1,
            confidentiality="CONFIDENTIAL",
            status="CURRENT",
        )
        db.add(document)
        db.commit()
        document_id = document.id
    try:
        body = client.get("/competition/evaluation?include_cases=true").json()
        assert "CUSTOMER-SECRET-MUST-NOT-LEAK" not in json.dumps(body)
        assert body["status"] == "PASSED"
    finally:
        with SessionLocal() as db:
            row = db.get(KnowledgeDocument, document_id)
            if row is not None:
                db.delete(row)
                db.commit()


def test_submission_evidence_fails_closed_without_signed_ci_artifact(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        competition_module, "RELEASE_EVIDENCE_PATH", tmp_path / "missing-release-evidence.json"
    )
    body = client.get("/competition/submission-evidence?lang=zh").json()
    assert body["phase"] == "V6.0"
    assert body["release"]["product_version"] == "V6.0"
    assert body["release"]["evidence_status"] == "UNVERIFIED"
    assert body["release"]["passed_cases"] == 0
    assert body["release"]["total_cases"] == 57
    assert body["release"]["ci"]["api_tests_passed"] is None
    assert all(row["status"] == "UNVERIFIED" for row in body["evaluation_suites"])
    assert all(row["passed_cases"] == 0 for row in body["evaluation_suites"])
    assert len(body["capabilities"]) == 6
    assert len(body["scorecard"]) == 10
    assert sum(row["max_score"] for row in body["scorecard"]) == 100


def test_submission_evidence_exposes_safe_lineage_and_unverified_reason(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        competition_module, "RELEASE_EVIDENCE_PATH", tmp_path / "missing-release-evidence.json"
    )
    body = client.get("/competition/submission-evidence").json()
    governance = body["governance"]
    assert len(governance["evidence_digest"]) == 64
    assert set(governance["dataset_hashes"]) == {
        "ai_outbound",
        "agent_organization",
        "assistant_dispatch",
    }
    assert all(len(value) == 64 for value in governance["dataset_hashes"].values())
    assert "api_key" not in str(governance["model_routing"]).lower()
    assert governance["external_delivery_performed"] is False
    assert "RELEASE_EVIDENCE_MISSING" in governance["evidence_verification"]["reasons"]


def test_submission_evidence_requires_authentic_artifact_and_reports_runner_failure(client, monkeypatch, tmp_path):
    key = "release-evidence-test-key-32-bytes-minimum"
    monkeypatch.setenv("GIT_COMMIT_SHA", "test-deploy-commit")
    monkeypatch.setattr(competition_module.settings, "evidence_signing_key", key)

    path, envelope = _release_artifact(tmp_path, key=key)
    monkeypatch.setattr(competition_module, "RELEASE_EVIDENCE_PATH", path)
    verified = client.get("/competition/submission-evidence").json()
    assert verified["release"]["evidence_status"] == "VERIFIED_PASSED"
    assert verified["release"]["passed_cases"] == 57
    assert all(row["status"] == "VERIFIED_PASSED" for row in verified["evaluation_suites"])
    bundle = client.get("/competition/evidence-bundle")
    assert bundle.status_code == 200
    assert bundle.json()["envelope"]["signature"]["key_id"] == "test-release:v1"

    original_bytes = path.read_bytes()
    replaced_bytes = original_bytes.replace(b'"test_metric": 1.0', b'"test_metric": 9.0')
    original_read_bytes = Path.read_bytes
    reads = 0

    def changing_read_bytes(target):
        nonlocal reads
        if target == path:
            reads += 1
            return original_bytes if reads == 1 else replaced_bytes
        return original_read_bytes(target)

    with monkeypatch.context() as context:
        context.setattr(Path, "read_bytes", changing_read_bytes)
        changed = client.get("/competition/evidence-bundle")
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "RELEASE_EVIDENCE_CHANGED"

    envelope["payload"]["suites"][0]["metrics"]["test_metric"] = 2.0
    path.write_text(json.dumps(envelope), encoding="utf-8")
    tampered = client.get("/competition/submission-evidence").json()
    assert tampered["release"]["evidence_status"] == "UNVERIFIED"
    assert "SIGNATURE_MISMATCH" in tampered["governance"]["evidence_verification"]["reasons"]
    rejected_bundle = client.get("/competition/evidence-bundle")
    assert rejected_bundle.status_code == 409
    assert rejected_bundle.json()["detail"]["code"] == "RELEASE_EVIDENCE_UNVERIFIED"
    assert "envelope" not in rejected_bundle.json()

    failed_path, _ = _release_artifact(
        tmp_path,
        key=key,
        failed_suite="AGENT_ORGANIZATION",
    )
    monkeypatch.setattr(competition_module, "RELEASE_EVIDENCE_PATH", failed_path)
    failed = client.get("/competition/submission-evidence").json()
    assert failed["release"]["evidence_status"] == "VERIFIED_FAILED"
    statuses = {row["id"]: row["status"] for row in failed["evaluation_suites"]}
    assert statuses["agent-organization"] == "VERIFIED_FAILED"


def test_production_readiness_verifies_artifact_commit_datasets_and_all_ci_gates(
    client, monkeypatch, tmp_path
):
    key = "release-evidence-test-key-32-bytes-minimum"
    monkeypatch.setenv("GIT_COMMIT_SHA", "test-deploy-commit")
    monkeypatch.setattr(competition_module.settings, "evidence_signing_key", key)
    monkeypatch.setattr(competition_module.settings, "evidence_allow_legacy_hmac", True)

    monkeypatch.setattr(
        competition_module,
        "RELEASE_EVIDENCE_PATH",
        tmp_path / "missing-release-evidence.json",
    )
    missing = client.get("/platform/production-readiness").json()
    assert missing["status"] == "NOT_READY"
    assert missing["controls"]["release_evidence_mounted"] is False
    assert missing["controls"]["release_evidence_authenticated"] is False
    assert missing["controls"]["release_validation_gates"] is False

    path, envelope = _release_artifact(tmp_path, key=key)
    monkeypatch.setattr(competition_module, "RELEASE_EVIDENCE_PATH", path)
    verified = client.get("/platform/production-readiness").json()
    assert verified["controls"]["release_evidence_verifier_configured"] is True
    assert verified["controls"]["release_evidence_mounted"] is True
    assert verified["controls"]["release_evidence_authenticated"] is True
    assert verified["controls"]["release_validation_gates"] is True
    assert verified["controls"]["release_suite_results"] is True
    assert all(verified["release_evidence"]["validation_checks"].values())

    monkeypatch.delenv("GIT_COMMIT_SHA")
    missing_commit = client.get("/platform/production-readiness").json()
    assert missing_commit["controls"]["release_evidence_authenticated"] is False
    assert "DEPLOYMENT_COMMIT_MISSING" in missing_commit["release_evidence"]["verification"]["reasons"]
    monkeypatch.setenv("GIT_COMMIT_SHA", "different-deploy-commit")
    wrong_commit = client.get("/platform/production-readiness").json()
    assert wrong_commit["controls"]["release_evidence_authenticated"] is False
    assert "COMMIT_MISMATCH" in wrong_commit["release_evidence"]["verification"]["reasons"]
    monkeypatch.setenv("GIT_COMMIT_SHA", "test-deploy-commit")

    envelope["payload"]["suites"][0]["dataset"]["sha256"] = "0" * 64
    dataset_mismatch = sign_release_payload(
        envelope["payload"], hmac_key=key, key_id="test-release:v1"
    )
    write_release_evidence(path, dataset_mismatch)
    stale_dataset = client.get("/platform/production-readiness").json()
    assert stale_dataset["controls"]["release_evidence_authenticated"] is False
    assert any(
        reason.startswith("DATASET_DIGEST_MISMATCH:")
        for reason in stale_dataset["release_evidence"]["verification"]["reasons"]
    )

    for failed_gate in (
        "api_tests",
        "web_build",
        "migration_check",
        "full_stack_smoke",
    ):
        failed_path, _ = _release_artifact(
            tmp_path,
            key=key,
            failed_validation=failed_gate,
        )
        monkeypatch.setattr(competition_module, "RELEASE_EVIDENCE_PATH", failed_path)
        failed = client.get("/platform/production-readiness").json()
        assert failed["controls"]["release_evidence_authenticated"] is True
        assert failed["controls"]["release_validation_gates"] is False
        assert failed["release_evidence"]["validation_checks"][failed_gate] is False
        assert failed["status"] == "NOT_READY"


def test_legacy_one_click_autorun_is_removed(client):
    response = client.post(
        "/competition/golden-thread/run",
        json={"human_approval_confirmed": True, "approver": "Anyone"},
    )
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "LEGACY_AUTORUN_REMOVED"


def test_role_ticketed_sandbox_runs_full_separated_golden_thread(client):
    created = _new_session(client)
    session_id = created["session"]["id"]
    tickets = created["role_tickets"]
    assert created["state"]["case"]["twin_id"] == SANDBOX_TWIN_ID
    assert created["state"]["session"]["shared_history"] is False

    analyzed = client.post(
        f"/competition/sessions/{session_id}/analyze",
        headers=_header(tickets["project_manager"]["ticket"]),
    )
    assert analyzed.status_code == 200, analyzed.text
    state = analyzed.json()
    assert {row["required_role"] for row in state["approvals"]} == {
        "project_manager",
        "hse_manager",
    }
    approvals = {row["required_role"]: row for row in state["approvals"]}

    # Sandbox records share only the synthetic project fixture; their case
    # organization keeps them out of ordinary tenant workspaces and queues.
    assert state["action"]["id"] not in {
        row["id"] for row in client.get("/actions").json()
    }
    assert not ({row["id"] for row in state["approvals"]} & {
        row["id"] for row in client.get("/approvals").json()
    })
    assert state["case"]["id"] not in {
        row["id"] for row in client.get("/projects/1/workspace").json()["cases"]
    }

    wrong_role = client.post(
        f"/competition/sessions/{session_id}/approvals/{approvals['hse_manager']['id']}/approve",
        headers=_header(tickets["project_manager"]["ticket"]),
    )
    assert wrong_role.status_code == 403
    assert wrong_role.json()["detail"]["code"] == "REQUIRED_APPROVER_ROLE_MISMATCH"

    pm = client.post(
        f"/competition/sessions/{session_id}/approvals/{approvals['project_manager']['id']}/approve",
        headers=_header(tickets["project_manager"]["ticket"]),
    )
    assert pm.status_code == 200, pm.text
    hse = client.post(
        f"/competition/sessions/{session_id}/approvals/{approvals['hse_manager']['id']}/approve",
        headers=_header(tickets["hse_manager"]["ticket"]),
    )
    assert hse.status_code == 200, hse.text
    assert hse.json()["action"]["status"] == "APPROVED"

    executed = client.post(
        f"/competition/sessions/{session_id}/execute",
        headers=_header(tickets["engineer"]["ticket"]),
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["receipts"]["execution"]["status"] == "SUCCEEDED"
    assert executed.json()["receipts"]["artifact"]["delivery_status"] == "DRAFT_ONLY_NOT_SENT"

    verified = client.post(
        f"/competition/sessions/{session_id}/verify",
        headers=_header(tickets["verifier"]["ticket"]),
    )
    assert verified.status_code == 200, verified.text
    verification = verified.json()["receipts"]["verification"]
    assert verification["status"] == "VERIFIED"
    assert all(verification["checks"].values())
    assert verification["signature"]

    replayed = client.post(
        f"/competition/sessions/{session_id}/execute",
        headers=_header(tickets["engineer"]["ticket"]),
    )
    assert replayed.status_code == 200
    assert replayed.json()["action"]["status"] == "VERIFIED"
    assert replayed.json()["session"]["status"] == "VERIFIED"

    closed = client.post(
        f"/competition/sessions/{session_id}/close",
        headers=_header(tickets["closer"]["ticket"]),
    )
    assert closed.status_code == 200, closed.text
    final = closed.json()
    assert final["complete"] is True
    assert final["case"]["status"] == "CLOSED"
    actors = {
        *(row["decided_by"] for row in final["approvals"]),
        final["receipts"]["execution"]["executor"],
        final["receipts"]["verification"]["verified_by"],
        final["action"]["closed_by"],
    }
    assert len(actors) == 5
    receipt_key_ids = {
        *(row["key_id"] for row in final["approvals"]),
        final["receipts"]["execution"]["key_id"],
        final["receipts"]["verification"]["key_id"],
        final["action"]["closure_key_id"],
    }
    assert len(receipt_key_ids) == 1
    assert None not in receipt_key_ids
    assert final["governance"]["external_delivery_performed"] is False

    reapprove = client.post(
        f"/competition/sessions/{session_id}/approvals/{approvals['project_manager']['id']}/approve",
        headers=_header(tickets["project_manager"]["ticket"]),
    )
    assert reapprove.status_code == 409
    assert reapprove.json()["detail"]["code"] == "ACTION_TERMINAL"
    reanalyze = client.post(
        f"/competition/sessions/{session_id}/analyze",
        headers=_header(tickets["project_manager"]["ticket"]),
    )
    assert reanalyze.status_code == 409
    assert reanalyze.json()["detail"]["code"] == "ACTION_TERMINAL"
    for operation, role in (
        ("execute", "engineer"),
        ("verify", "verifier"),
        ("close", "closer"),
    ):
        immutable = client.post(
            f"/competition/sessions/{session_id}/{operation}",
            headers=_header(tickets[role]["ticket"]),
        )
        assert immutable.status_code == 409
        assert immutable.json()["detail"]["code"] == "ACTION_TERMINAL"
    assert client.get(
        f"/competition/sessions/{session_id}/state",
        headers=_header(tickets["project_manager"]["ticket"]),
    ).json()["complete"] is True


def test_sandbox_never_reuses_tenant_project_or_private_documents(client):
    private_ref = "TENANT-PRIVATE-P47-MUST-NOT-ENTER-SANDBOX"
    with SessionLocal() as db:
        document = KnowledgeDocument(
            title={"en": "Private P47 working-at-height instruction", "zh": "私有文档"},
            category={"en": "Customer", "zh": "客户"},
            jurisdiction={"en": "Project", "zh": "项目"},
            language={"en": "English", "zh": "英语"},
            source_ref=private_ref,
            content={
                "en": "P47 unprotected edge fall protection permit competent person",
                "zh": "客户私有内容",
            },
            summary={"en": "tenant confidential", "zh": "客户机密"},
            project_id=1,
            confidentiality="CONFIDENTIAL",
            status="CURRENT",
        )
        db.add(document)
        db.commit()
        document_id = document.id
    try:
        created = _new_session(client)
        session_id = created["session"]["id"]
        analyzed = client.post(
            f"/competition/sessions/{session_id}/analyze",
            headers=_header(created["role_tickets"]["project_manager"]["ticket"]),
        )
        assert analyzed.status_code == 200, analyzed.text
        case_id = analyzed.json()["case"]["id"]
        with SessionLocal() as db:
            case = db.get(Case, case_id)
            project = db.get(Project, case.project_id)
            refs = set(
                db.scalars(
                    select(Evidence.source_ref).where(Evidence.case_id == case_id)
                )
            )
        assert project.id != 1
        assert project.organization_id == SANDBOX_ORGANIZATION_ID
        assert private_ref not in refs
    finally:
        with SessionLocal() as db:
            row = db.get(KnowledgeDocument, document_id)
            if row is not None:
                db.delete(row)
                db.commit()


def test_sandbox_tickets_are_session_bound_and_reset_is_fresh(client):
    first = _new_session(client)
    second = _new_session(client)
    first_id = first["session"]["id"]
    second_id = second["session"]["id"]
    first_pm = first["role_tickets"]["project_manager"]["ticket"]

    cross_session = client.post(
        f"/competition/sessions/{second_id}/analyze",
        headers=_header(first_pm),
    )
    assert cross_session.status_code == 401
    assert cross_session.json()["detail"]["code"] == "INVALID_ROLE_TICKET"

    reset = client.post(
        f"/competition/sessions/{first_id}/reset", headers=_header(first_pm)
    )
    assert reset.status_code == 201, reset.text
    replacement = reset.json()
    assert replacement["session"]["id"] != first_id
    assert replacement["session"]["case_id"] != first["session"]["case_id"]
    assert replacement["session"]["snapshot_digest"] == first["session"]["snapshot_digest"]
    assert replacement["session"]["reset_count"] == 1

    retired = client.get(
        f"/competition/sessions/{first_id}/state", headers=_header(first_pm)
    )
    assert retired.status_code == 410


def test_v6_closer_cannot_reuse_an_approver_identity(client):
    created, action_id = _verified_session(client)
    approver_subject = created["role_tickets"]["project_manager"]["subject"]

    with SessionLocal() as db:
        with pytest.raises(GovernedExecutionError) as raised:
            close_action(
                db,
                action_id,
                approver_subject,
                closer_roles={"project_manager"},
            )

    assert raised.value.code == "SEPARATION_OF_DUTIES_REQUIRED"


@pytest.mark.parametrize(
    ("receipt_model", "field", "tampered_value"),
    (
        (ExecutionReceipt, "executor", "tampered.executor"),
        (VerificationReceipt, "verified_by", "tampered.verifier"),
    ),
)
def test_signed_receipt_field_tampering_blocks_closure(
    client, receipt_model, field, tampered_value
):
    created, action_id = _verified_session(client)
    session_id = created["session"]["id"]
    tickets = created["role_tickets"]

    with SessionLocal() as db:
        receipt = db.scalar(
            select(receipt_model).where(receipt_model.action_id == action_id)
        )
        assert receipt is not None
        setattr(receipt, field, tampered_value)
        db.commit()

    close = client.post(
        f"/competition/sessions/{session_id}/close",
        headers=_header(tickets["closer"]["ticket"]),
    )
    assert close.status_code == 409
    assert close.json()["detail"]["code"] == "RECEIPT_CHAIN_INTEGRITY_FAILED"


def test_artifact_tampering_is_detected_before_closure(client):
    created = _new_session(client)
    session_id = created["session"]["id"]
    tickets = created["role_tickets"]
    state = client.post(
        f"/competition/sessions/{session_id}/analyze",
        headers=_header(tickets["project_manager"]["ticket"]),
    ).json()
    approvals = {row["required_role"]: row for row in state["approvals"]}
    for role in ("project_manager", "hse_manager"):
        state = client.post(
            f"/competition/sessions/{session_id}/approvals/{approvals[role]['id']}/approve",
            headers=_header(tickets[role]["ticket"]),
        ).json()
    executed = client.post(
        f"/competition/sessions/{session_id}/execute",
        headers=_header(tickets["engineer"]["ticket"]),
    )
    assert executed.status_code == 200
    action_id = executed.json()["action"]["id"]
    with SessionLocal() as db:
        artifact = db.scalar(select(Artifact).where(Artifact.action_id == action_id))
        artifact.content = artifact.content + "\nTAMPERED"
        db.commit()

    verification = client.post(
        f"/competition/sessions/{session_id}/verify",
        headers=_header(tickets["verifier"]["ticket"]),
    )
    assert verification.status_code == 200
    body = verification.json()
    assert body["receipts"]["verification"]["status"] == "VERIFICATION_FAILED"
    assert body["receipts"]["verification"]["checks"]["artifact_digest"] is False
    assert body["next_steps"] == ["verify"]

    close = client.post(
        f"/competition/sessions/{session_id}/close",
        headers=_header(tickets["closer"]["ticket"]),
    )
    assert close.status_code == 409
    assert close.json()["detail"]["code"] == "VERIFICATION_REQUIRED"


def test_artifact_tampering_after_verification_blocks_closure(client):
    created = _new_session(client)
    session_id = created["session"]["id"]
    tickets = created["role_tickets"]
    state = client.post(
        f"/competition/sessions/{session_id}/analyze",
        headers=_header(tickets["project_manager"]["ticket"]),
    ).json()
    approvals = {row["required_role"]: row for row in state["approvals"]}
    for role in ("project_manager", "hse_manager"):
        client.post(
            f"/competition/sessions/{session_id}/approvals/{approvals[role]['id']}/approve",
            headers=_header(tickets[role]["ticket"]),
        )
    executed = client.post(
        f"/competition/sessions/{session_id}/execute",
        headers=_header(tickets["engineer"]["ticket"]),
    ).json()
    action_id = executed["action"]["id"]
    verified = client.post(
        f"/competition/sessions/{session_id}/verify",
        headers=_header(tickets["verifier"]["ticket"]),
    )
    assert verified.status_code == 200
    assert verified.json()["receipts"]["verification"]["status"] == "VERIFIED"

    with SessionLocal() as db:
        artifact = db.scalar(select(Artifact).where(Artifact.action_id == action_id))
        artifact.content += "\nPOST-VERIFICATION-TAMPER"
        db.commit()

    close = client.post(
        f"/competition/sessions/{session_id}/close",
        headers=_header(tickets["closer"]["ticket"]),
    )
    assert close.status_code == 409
    assert close.json()["detail"]["code"] == "RECEIPT_CHAIN_INTEGRITY_FAILED"


def test_legacy_golden_snapshot_stays_read_only_and_uses_p47(client):
    response = client.get("/competition/golden-thread?lang=zh")
    assert response.status_code == 200
    body = response.json()
    assert body["case"]["id"] == GOLDEN_CASE_ID
    assert "P47" in body["case"]["title"]
