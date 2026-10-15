"""assistant conversation memory

Revision ID: 0014
Revises: 0013

The dispatching assistant keeps each conversation's recent turns and its
current case and project on the server, so follow-ups such as "this case"
resolve after a page reload.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assistant_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("turns", sa.JSON(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_assistant_sessions_organization_id", "assistant_sessions", ["organization_id"])
    op.create_index("ix_assistant_sessions_subject", "assistant_sessions", ["subject"])


def downgrade() -> None:
    op.drop_table("assistant_sessions")
