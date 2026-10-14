"""unified six-channel data ingestion control plane

Revision ID: 0009
Revises: 0008
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_receipts",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(48), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("records_received", sa.Integer(), nullable=False),
        sa.Column("records_accepted", sa.Integer(), nullable=False),
        sa.Column("records_rejected", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(96), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("mapping_version", sa.String(64), nullable=False),
        sa.Column("validation_summary", sa.JSON(), nullable=False),
        sa.Column("lineage", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    for column in ("organization_id", "project_id", "channel", "source_type", "status", "target_id", "created_at"):
        op.create_index(f"ix_ingestion_receipts_{column}", "ingestion_receipts", [column])


def downgrade() -> None:
    op.drop_table("ingestion_receipts")
