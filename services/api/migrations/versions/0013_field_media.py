"""validated original field media

Revision ID: 0013
Revises: 0012

Field photos, videos and voice notes are uploaded, validated by file
signature and stored content-addressed by SHA-256 until an object store is
configured.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "field_media",
        sa.Column("sha256", sa.String(length=64), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=80), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_field_media_organization_id", "field_media", ["organization_id"])


def downgrade() -> None:
    op.drop_table("field_media")
