"""field observation analysis status and AI risk

Revision ID: 0012
Revises: 0011

Field reports now go through intake classification and the agent
organization. Existing reports were never analysed and are marked
NOT_ANALYZED.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("field_observations", sa.Column("analysis_status", sa.String(length=16), nullable=False, server_default="NOT_ANALYZED"))
    op.add_column("field_observations", sa.Column("ai_risk", sa.String(length=20), nullable=True))
    op.create_index("ix_field_observations_analysis_status", "field_observations", ["analysis_status"])


def downgrade() -> None:
    op.drop_index("ix_field_observations_analysis_status", table_name="field_observations")
    op.drop_column("field_observations", "ai_risk")
    op.drop_column("field_observations", "analysis_status")
