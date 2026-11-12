"""V6 separation of duties, signed receipts and isolated judge sandbox.

Revision ID: 0015
Revises: 0014
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _recreate() -> str:
    return "always" if op.get_bind().dialect.name == "sqlite" else "auto"


def upgrade() -> None:
    with op.batch_alter_table("projects", recreate=_recreate()) as batch:
        batch.add_column(
            sa.Column(
                "organization_id",
                sa.String(length=64),
                nullable=True,
            )
        )

    # Only the bundled fixtures are known to belong to the demo tenant.  Any
    # pre-existing customer project must be reviewed explicitly instead of
    # being silently reassigned to that tenant during the upgrade.
    op.execute(
        sa.text(
            """
            UPDATE projects
            SET organization_id = CASE
                WHEN code IN ('MY-RAIL-A', 'ID-HWY-B', 'SA-METRO-C')
                    THEN 'globalinfra-demo'
                ELSE 'MIGRATION_REVIEW_REQUIRED'
            END
            WHERE organization_id IS NULL
            """
        )
    )
    with op.batch_alter_table("projects", recreate=_recreate()) as batch:
        batch.alter_column(
            "organization_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch.create_index("ix_projects_organization_id", ["organization_id"])

    with op.batch_alter_table("cases", recreate=_recreate()) as batch:
        batch.add_column(
            sa.Column(
                "organization_id",
                sa.String(length=64),
                nullable=True,
            )
        )

    # A routed case inherits its owning project tenant.  Orphaned or otherwise
    # unmappable legacy rows are quarantined for an operator-led migration.
    op.execute(
        sa.text(
            """
            UPDATE cases
            SET organization_id = (
                SELECT projects.organization_id
                FROM projects
                WHERE projects.id = cases.project_id
            )
            WHERE organization_id IS NULL
              AND project_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM projects WHERE projects.id = cases.project_id
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE cases
            SET organization_id = 'MIGRATION_REVIEW_REQUIRED'
            WHERE organization_id IS NULL
            """
        )
    )
    with op.batch_alter_table("cases", recreate=_recreate()) as batch:
        batch.alter_column(
            "organization_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch.create_index("ix_cases_organization_id", ["organization_id"])

    with op.batch_alter_table("intake_submissions", recreate=_recreate()) as batch:
        batch.add_column(sa.Column("organization_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_intake_submissions_project_id",
            "projects",
            ["project_id"],
            ["id"],
        )
    op.execute(
        sa.text(
            """
            UPDATE intake_submissions
            SET organization_id = (
                    SELECT cases.organization_id FROM cases
                    WHERE cases.id = intake_submissions.case_id
                ),
                project_id = (
                    SELECT cases.project_id FROM cases
                    WHERE cases.id = intake_submissions.case_id
                )
            WHERE case_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM cases WHERE cases.id = intake_submissions.case_id
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE intake_submissions
            SET organization_id = 'MIGRATION_REVIEW_REQUIRED'
            WHERE organization_id IS NULL
            """
        )
    )
    with op.batch_alter_table("intake_submissions", recreate=_recreate()) as batch:
        batch.alter_column(
            "organization_id", existing_type=sa.String(64), nullable=False
        )
        batch.create_index(
            "ix_intake_submissions_organization_id", ["organization_id"]
        )
        batch.create_index("ix_intake_submissions_project_id", ["project_id"])

    with op.batch_alter_table("source_documents", recreate=_recreate()) as batch:
        batch.add_column(sa.Column("organization_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_source_documents_project_id",
            "projects",
            ["project_id"],
            ["id"],
        )
    op.execute(
        sa.text(
            """
            UPDATE source_documents
            SET organization_id = (
                    SELECT intake_submissions.organization_id
                    FROM intake_submissions
                    WHERE intake_submissions.id = source_documents.intake_submission_id
                ),
                project_id = (
                    SELECT intake_submissions.project_id
                    FROM intake_submissions
                    WHERE intake_submissions.id = source_documents.intake_submission_id
                )
            WHERE EXISTS (
                SELECT 1 FROM intake_submissions
                WHERE intake_submissions.id = source_documents.intake_submission_id
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE source_documents
            SET organization_id = 'MIGRATION_REVIEW_REQUIRED'
            WHERE organization_id IS NULL
            """
        )
    )
    with op.batch_alter_table("source_documents", recreate=_recreate()) as batch:
        batch.alter_column(
            "organization_id", existing_type=sa.String(64), nullable=False
        )
        batch.create_index(
            "ix_source_documents_organization_id", ["organization_id"]
        )
        batch.create_index("ix_source_documents_project_id", ["project_id"])

    with op.batch_alter_table("field_media", recreate=_recreate()) as batch:
        batch.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_field_media_project_id",
            "projects",
            ["project_id"],
            ["id"],
        )
        batch.create_index("ix_field_media_project_id", ["project_id"])

    op.create_table(
        "field_media_grants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["sha256"], ["field_media.sha256"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.UniqueConstraint(
            "sha256", "organization_id", "project_id",
            name="uq_field_media_grant_scope",
        ),
    )
    op.create_index(
        "ix_field_media_grants_sha256", "field_media_grants", ["sha256"]
    )
    op.create_index(
        "ix_field_media_grants_organization_id",
        "field_media_grants",
        ["organization_id"],
    )
    op.create_index(
        "ix_field_media_grants_project_id", "field_media_grants", ["project_id"]
    )
    # Only media with an unambiguous legacy project receives a grant. Unknown
    # rows remain inaccessible until the original bytes are re-uploaded by an
    # authenticated user to an authorized project.
    op.execute(
        sa.text(
            """
            INSERT INTO field_media_grants
                (sha256, organization_id, project_id, uploaded_by, created_at)
            SELECT sha256, organization_id, project_id, uploaded_by, created_at
            FROM field_media
            WHERE project_id IS NOT NULL
            """
        )
    )

    op.create_table(
        "competition_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("reset_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_digest", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
    )
    op.create_index(
        "ix_competition_sessions_case_id",
        "competition_sessions",
        ["case_id"],
        unique=True,
    )
    op.create_index(
        "ix_competition_sessions_organization_id",
        "competition_sessions",
        ["organization_id"],
    )
    op.create_index(
        "ix_competition_sessions_status", "competition_sessions", ["status"]
    )
    op.create_index(
        "ix_competition_sessions_expires_at",
        "competition_sessions",
        ["expires_at"],
    )

    with op.batch_alter_table("approvals", recreate=_recreate()) as batch:
        batch.add_column(sa.Column("sandbox_session_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("required_role", sa.String(40), nullable=True))
        batch.add_column(
            sa.Column(
                "policy_version",
                sa.String(64),
                nullable=False,
                server_default="legacy.v5",
            )
        )
        batch.add_column(sa.Column("decided_role", sa.String(40), nullable=True))
        batch.add_column(sa.Column("decision_digest", sa.String(64), nullable=True))
        batch.add_column(sa.Column("decision_signature", sa.String(128), nullable=True))
        batch.add_column(sa.Column("decision_key_id", sa.String(80), nullable=True))
        batch.create_foreign_key(
            "fk_approvals_sandbox_session_id",
            "competition_sessions",
            ["sandbox_session_id"],
            ["id"],
        )
        batch.create_index("ix_approvals_sandbox_session_id", ["sandbox_session_id"])
        batch.create_index("ix_approvals_required_role", ["required_role"])
        batch.create_index("ix_approvals_policy_version", ["policy_version"])

    with op.batch_alter_table("actions", recreate=_recreate()) as batch:
        batch.add_column(
            sa.Column(
                "policy_version",
                sa.String(64),
                nullable=False,
                server_default="legacy.v5",
            )
        )
        batch.add_column(sa.Column("proposed_by", sa.String(120), nullable=True))
        batch.add_column(sa.Column("proposal_digest", sa.String(64), nullable=True))
        batch.add_column(sa.Column("closed_by", sa.String(120), nullable=True))
        batch.add_column(sa.Column("closed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("closure_digest", sa.String(64), nullable=True))
        batch.add_column(sa.Column("closure_signature", sa.String(128), nullable=True))
        batch.add_column(sa.Column("closure_key_id", sa.String(80), nullable=True))
        batch.create_index("ix_actions_policy_version", ["policy_version"])

    with op.batch_alter_table("execution_receipts", recreate=_recreate()) as batch:
        batch.add_column(sa.Column("executor_role", sa.String(40), nullable=True))
        batch.add_column(
            sa.Column(
                "policy_version",
                sa.String(64),
                nullable=False,
                server_default="legacy.v5",
            )
        )
        batch.add_column(sa.Column("receipt_digest", sa.String(64), nullable=True))
        batch.add_column(sa.Column("receipt_signature", sa.String(128), nullable=True))
        batch.add_column(sa.Column("key_id", sa.String(80), nullable=True))
        batch.create_index("ix_execution_receipts_policy_version", ["policy_version"])

    with op.batch_alter_table("verification_receipts", recreate=_recreate()) as batch:
        batch.add_column(sa.Column("verified_by", sa.String(120), nullable=True))
        batch.add_column(sa.Column("verifier_role", sa.String(40), nullable=True))
        batch.add_column(
            sa.Column(
                "policy_version",
                sa.String(64),
                nullable=False,
                server_default="legacy.v5",
            )
        )
        batch.add_column(sa.Column("verification_digest", sa.String(64), nullable=True))
        batch.add_column(sa.Column("verification_signature", sa.String(128), nullable=True))
        batch.add_column(sa.Column("key_id", sa.String(80), nullable=True))
        batch.create_index("ix_verification_receipts_policy_version", ["policy_version"])

    with op.batch_alter_table("country_packs", recreate=_recreate()) as batch:
        batch.add_column(sa.Column("reviewed_by", sa.String(120), nullable=True))
        batch.add_column(sa.Column("review_due_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("source_digest", sa.String(64), nullable=True))
        batch.create_index("ix_country_packs_review_due_at", ["review_due_at"])

    op.create_table(
        "pilot_measurements",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("metric_name", sa.String(80), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("baseline_value", sa.Float(), nullable=False),
        sa.Column("assisted_value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("evidence_ref", sa.String(255), nullable=False),
        sa.Column("evidence_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("recorded_by", sa.String(120), nullable=False),
        sa.Column("verified_by", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    op.create_index("ix_pilot_measurements_organization_id", "pilot_measurements", ["organization_id"])
    op.create_index("ix_pilot_measurements_project_id", "pilot_measurements", ["project_id"])
    op.create_index("ix_pilot_measurements_metric_name", "pilot_measurements", ["metric_name"])
    op.create_index("ix_pilot_measurements_evidence_digest", "pilot_measurements", ["evidence_digest"])
    op.create_index("ix_pilot_measurements_status", "pilot_measurements", ["status"])


def downgrade() -> None:
    for index in (
        "ix_pilot_measurements_status",
        "ix_pilot_measurements_evidence_digest",
        "ix_pilot_measurements_metric_name",
        "ix_pilot_measurements_project_id",
        "ix_pilot_measurements_organization_id",
    ):
        op.drop_index(index, table_name="pilot_measurements")
    op.drop_table("pilot_measurements")

    with op.batch_alter_table("country_packs", recreate=_recreate()) as batch:
        batch.drop_index("ix_country_packs_review_due_at")
        batch.drop_column("source_digest")
        batch.drop_column("review_due_at")
        batch.drop_column("reviewed_by")

    with op.batch_alter_table("verification_receipts", recreate=_recreate()) as batch:
        batch.drop_index("ix_verification_receipts_policy_version")
        for column in (
            "key_id",
            "verification_signature",
            "verification_digest",
            "policy_version",
            "verifier_role",
            "verified_by",
        ):
            batch.drop_column(column)

    with op.batch_alter_table("execution_receipts", recreate=_recreate()) as batch:
        batch.drop_index("ix_execution_receipts_policy_version")
        for column in (
            "key_id",
            "receipt_signature",
            "receipt_digest",
            "policy_version",
            "executor_role",
        ):
            batch.drop_column(column)

    with op.batch_alter_table("actions", recreate=_recreate()) as batch:
        batch.drop_index("ix_actions_policy_version")
        for column in (
            "closure_key_id",
            "closure_signature",
            "closure_digest",
            "closed_at",
            "closed_by",
            "proposal_digest",
            "proposed_by",
            "policy_version",
        ):
            batch.drop_column(column)

    with op.batch_alter_table("approvals", recreate=_recreate()) as batch:
        batch.drop_index("ix_approvals_policy_version")
        batch.drop_index("ix_approvals_required_role")
        batch.drop_index("ix_approvals_sandbox_session_id")
        batch.drop_constraint("fk_approvals_sandbox_session_id", type_="foreignkey")
        for column in (
            "decision_key_id",
            "decision_signature",
            "decision_digest",
            "decided_role",
            "policy_version",
            "required_role",
            "sandbox_session_id",
        ):
            batch.drop_column(column)

    for index in (
        "ix_competition_sessions_expires_at",
        "ix_competition_sessions_status",
        "ix_competition_sessions_organization_id",
        "ix_competition_sessions_case_id",
    ):
        op.drop_index(index, table_name="competition_sessions")
    op.drop_table("competition_sessions")

    for index in (
        "ix_field_media_grants_project_id",
        "ix_field_media_grants_organization_id",
        "ix_field_media_grants_sha256",
    ):
        op.drop_index(index, table_name="field_media_grants")
    op.drop_table("field_media_grants")

    with op.batch_alter_table("field_media", recreate=_recreate()) as batch:
        batch.drop_index("ix_field_media_project_id")
        batch.drop_constraint("fk_field_media_project_id", type_="foreignkey")
        batch.drop_column("project_id")

    with op.batch_alter_table("source_documents", recreate=_recreate()) as batch:
        batch.drop_index("ix_source_documents_project_id")
        batch.drop_index("ix_source_documents_organization_id")
        batch.drop_constraint("fk_source_documents_project_id", type_="foreignkey")
        batch.drop_column("project_id")
        batch.drop_column("organization_id")

    with op.batch_alter_table("intake_submissions", recreate=_recreate()) as batch:
        batch.drop_index("ix_intake_submissions_project_id")
        batch.drop_index("ix_intake_submissions_organization_id")
        batch.drop_constraint(
            "fk_intake_submissions_project_id", type_="foreignkey"
        )
        batch.drop_column("project_id")
        batch.drop_column("organization_id")

    with op.batch_alter_table("projects", recreate=_recreate()) as batch:
        batch.drop_index("ix_projects_organization_id")
        batch.drop_column("organization_id")

    with op.batch_alter_table("cases", recreate=_recreate()) as batch:
        batch.drop_index("ix_cases_organization_id")
        batch.drop_column("organization_id")
