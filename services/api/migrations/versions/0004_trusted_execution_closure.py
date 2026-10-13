"""trusted execution closure and evidence graph (V2.1)

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _batch_recreate_mode() -> str:
    """SQLite needs table recreation for added foreign keys; PostgreSQL does not."""
    return "always" if op.get_bind().dialect.name == "sqlite" else "auto"


def upgrade() -> None:
    # Intake must be able to remain unassigned until a human confirms routing.
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("cases", recreate="always") as batch_op:
            batch_op.alter_column("project_id", existing_type=sa.Integer(), nullable=True)
            batch_op.add_column(sa.Column("project_routing_confidence", sa.Float(), nullable=True))
            batch_op.add_column(sa.Column("routing_status", sa.String(length=40), nullable=False, server_default="ROUTED"))
    else:
        op.alter_column("cases", "project_id", existing_type=sa.Integer(), nullable=True)
        op.add_column("cases", sa.Column("project_routing_confidence", sa.Float(), nullable=True))
        op.add_column("cases", sa.Column("routing_status", sa.String(length=40), nullable=False, server_default="ROUTED"))

    op.create_table(
        "claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("statement", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
    )
    op.create_index("ix_claims_case_id", "claims", ["case_id"], unique=False)
    # SQLite cannot ALTER an existing table to add a foreign key.  Batch mode
    # keeps the migration valid for the local/test SQLite path while emitting a
    # normal ALTER on databases that support it.
    with op.batch_alter_table("evidence", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.add_column(sa.Column("claim_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_evidence_claim_id", "claims", ["claim_id"], ["id"])
        batch_op.create_index("ix_evidence_claim_id", ["claim_id"], unique=False)

    op.create_table(
        "actions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("approval_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=True),
        sa.Column("output_digest", sa.String(length=64), nullable=True),
        sa.Column("artifact_ref", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"]),
    )
    op.create_index("ix_actions_case_id", "actions", ["case_id"], unique=False)
    op.create_index("ix_actions_approval_id", "actions", ["approval_id"], unique=False)
    op.create_index("ix_actions_action_type", "actions", ["action_type"], unique=False)
    op.create_index("ix_actions_status", "actions", ["status"], unique=False)
    with op.batch_alter_table("approvals", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.add_column(sa.Column("action_id", sa.String(length=64), nullable=True))
        batch_op.create_foreign_key("fk_approvals_action_id", "actions", ["action_id"], ["id"])
        batch_op.create_index("ix_approvals_action_id", ["action_id"], unique=False)

    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=96), primary_key=True),
        sa.Column("action_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_ref", sa.String(length=255), nullable=False),
        sa.Column("artifact_type", sa.String(length=80), nullable=False),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"]),
        sa.UniqueConstraint("action_id"),
        sa.UniqueConstraint("artifact_ref"),
    )
    op.create_index("ix_artifacts_action_id", "artifacts", ["action_id"], unique=True)
    op.create_index("ix_artifacts_artifact_ref", "artifacts", ["artifact_ref"], unique=True)
    op.create_index("ix_artifacts_digest", "artifacts", ["digest"], unique=False)

    op.create_table(
        "execution_receipts",
        sa.Column("id", sa.String(length=96), primary_key=True),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("action_id", sa.String(length=64), nullable=False),
        sa.Column("approval_id", sa.Integer(), nullable=False),
        sa.Column("executor", sa.String(length=120), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("output_digest", sa.String(length=64), nullable=True),
        sa.Column("artifact_ref", sa.String(length=255), nullable=True),
        sa.Column("error_detail", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"]),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"]),
        sa.UniqueConstraint("action_id"),
    )
    op.create_index("ix_execution_receipts_case_id", "execution_receipts", ["case_id"], unique=False)
    op.create_index("ix_execution_receipts_action_id", "execution_receipts", ["action_id"], unique=True)
    op.create_index("ix_execution_receipts_approval_id", "execution_receipts", ["approval_id"], unique=False)
    op.create_index("ix_execution_receipts_status", "execution_receipts", ["status"], unique=False)

    op.create_table(
        "verification_receipts",
        sa.Column("id", sa.String(length=96), primary_key=True),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("action_id", sa.String(length=64), nullable=False),
        sa.Column("execution_receipt_id", sa.String(length=96), nullable=False),
        sa.Column("approval_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("artifact_ref", sa.String(length=255), nullable=True),
        sa.Column("artifact_digest", sa.String(length=64), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["action_id"], ["actions.id"]),
        sa.ForeignKeyConstraint(["execution_receipt_id"], ["execution_receipts.id"]),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"]),
        sa.UniqueConstraint("action_id"),
        sa.UniqueConstraint("execution_receipt_id"),
    )
    op.create_index("ix_verification_receipts_case_id", "verification_receipts", ["case_id"], unique=False)
    op.create_index("ix_verification_receipts_action_id", "verification_receipts", ["action_id"], unique=True)
    op.create_index("ix_verification_receipts_execution_receipt_id", "verification_receipts", ["execution_receipt_id"], unique=True)
    op.create_index("ix_verification_receipts_approval_id", "verification_receipts", ["approval_id"], unique=False)
    op.create_index("ix_verification_receipts_status", "verification_receipts", ["status"], unique=False)


def downgrade() -> None:
    for index in (
        "ix_verification_receipts_status", "ix_verification_receipts_approval_id",
        "ix_verification_receipts_execution_receipt_id", "ix_verification_receipts_action_id",
        "ix_verification_receipts_case_id",
    ):
        op.drop_index(index, table_name="verification_receipts")
    op.drop_table("verification_receipts")
    for index in ("ix_execution_receipts_status", "ix_execution_receipts_approval_id", "ix_execution_receipts_action_id", "ix_execution_receipts_case_id"):
        op.drop_index(index, table_name="execution_receipts")
    op.drop_table("execution_receipts")
    for index in ("ix_artifacts_digest", "ix_artifacts_artifact_ref", "ix_artifacts_action_id"):
        op.drop_index(index, table_name="artifacts")
    op.drop_table("artifacts")
    with op.batch_alter_table("approvals", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.drop_index("ix_approvals_action_id")
        batch_op.drop_constraint("fk_approvals_action_id", type_="foreignkey")
        batch_op.drop_column("action_id")
    for index in ("ix_actions_status", "ix_actions_action_type", "ix_actions_approval_id", "ix_actions_case_id"):
        op.drop_index(index, table_name="actions")
    op.drop_table("actions")
    with op.batch_alter_table("evidence", recreate=_batch_recreate_mode()) as batch_op:
        batch_op.drop_index("ix_evidence_claim_id")
        batch_op.drop_constraint("fk_evidence_claim_id", type_="foreignkey")
        batch_op.drop_column("claim_id")
    op.drop_index("ix_claims_case_id", table_name="claims")
    op.drop_table("claims")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("cases", recreate="always") as batch_op:
            batch_op.drop_column("routing_status")
            batch_op.drop_column("project_routing_confidence")
            batch_op.alter_column("project_id", existing_type=sa.Integer(), nullable=False)
    else:
        op.drop_column("cases", "routing_status")
        op.drop_column("cases", "project_routing_confidence")
        op.alter_column("cases", "project_id", existing_type=sa.Integer(), nullable=False)
