"""universal intake tables (V1.3 M1)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02

Adds the two tables that back the Universal Intake Foundation:
``intake_submissions`` (raw input reference, input hash, parsed text, detected
language, created-at, linked case_id) and ``source_documents`` (filename, file
type, storage reference, parse status, linked intake_submission_id). These are
also part of ``Base.metadata`` so the offline ``create_all`` path produces the
same schema without running Alembic.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "intake_submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raw_input_ref", sa.String(length=255), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("parsed_text", sa.Text(), nullable=False),
        sa.Column("detected_language", sa.String(length=8), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_intake_submissions_input_hash", "intake_submissions", ["input_hash"], unique=False)
    op.create_index("ix_intake_submissions_case_id", "intake_submissions", ["case_id"], unique=False)

    op.create_table(
        "source_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("intake_submission_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("storage_ref", sa.String(length=255), nullable=False),
        sa.Column("parse_status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["intake_submission_id"], ["intake_submissions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_documents_intake_submission_id", "source_documents", ["intake_submission_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_source_documents_intake_submission_id", table_name="source_documents")
    op.drop_table("source_documents")
    op.drop_index("ix_intake_submissions_case_id", table_name="intake_submissions")
    op.drop_index("ix_intake_submissions_input_hash", table_name="intake_submissions")
    op.drop_table("intake_submissions")
