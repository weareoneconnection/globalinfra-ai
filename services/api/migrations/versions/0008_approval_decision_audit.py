"""add approval decision audit fields

Revision ID: 0008
Revises: 0007
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("approvals") as batch:
        batch.add_column(sa.Column("decided_by", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("decided_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("approvals") as batch:
        batch.drop_column("decided_at")
        batch.drop_column("decided_by")
