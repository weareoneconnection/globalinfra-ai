"""preserve original source document content

Revision ID: 0010
Revises: 0009

Retains the validated original upload so image-only PDFs can be accepted into
the governed document queue and processed by a later OCR worker without asking
the user to upload the file again.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("source_documents", sa.Column("content_type", sa.String(length=160), nullable=True))
    op.add_column("source_documents", sa.Column("byte_size", sa.Integer(), nullable=True))
    op.add_column("source_documents", sa.Column("original_content", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("source_documents", "original_content")
    op.drop_column("source_documents", "byte_size")
    op.drop_column("source_documents", "content_type")
