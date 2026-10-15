"""agent organization traces and agent questions to humans

Revision ID: 0011
Revises: 0010

Agent organization 2.0 records each step of a multi-agent run (team
assembly with rationale, specialist rounds with tool calls and structured
findings, coordination, planning and verification) and the questions agents
ask a human when evidence is insufficient.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_traces",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.String(length=64), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("agent_id", sa.String(length=40), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("rationale", sa.JSON(), nullable=True),
        sa.Column("tool_calls", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("case_id", "run_id", "kind", "agent_id", "status"):
        op.create_index(f"ix_agent_traces_{column}", "agent_traces", [column])
    op.create_table(
        "case_inputs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.String(length=64), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("agent_id", sa.String(length=40), nullable=False),
        sa.Column("question_key", sa.String(length=120), nullable=False),
        sa.Column("question", sa.JSON(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("answered_by", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
    )
    for column in ("case_id", "question_key", "status"):
        op.create_index(f"ix_case_inputs_{column}", "case_inputs", [column])


def downgrade() -> None:
    op.drop_table("case_inputs")
    op.drop_table("agent_traces")
