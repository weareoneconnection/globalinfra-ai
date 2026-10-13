"""phase 8 operational digital twin

Revision ID: 0006
Revises: 0005
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("twin_profiles",
        sa.Column("project_id", sa.Integer(), primary_key=True), sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("slug", sa.String(96), nullable=False, unique=True), sa.Column("center", sa.JSON(), nullable=False),
        sa.Column("version", sa.String(80), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["project_id"], ["projects.id"]))
    op.create_index("ix_twin_profiles_slug", "twin_profiles", ["slug"], unique=True)
    op.create_table("twin_model_versions",
        sa.Column("id", sa.String(96), primary_key=True), sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(80), nullable=False), sa.Column("format", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("uri", sa.String(500), nullable=False), sa.Column("object_count", sa.Integer(), nullable=False),
        sa.Column("change_summary", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]))
    for column in ("project_id", "version", "status"):
        op.create_index(f"ix_twin_model_versions_{column}", "twin_model_versions", [column])
    op.create_table("twin_conversion_jobs",
        sa.Column("id", sa.String(96), primary_key=True), sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("input_format", sa.String(24), nullable=False), sa.Column("input_ref", sa.String(500), nullable=False),
        sa.Column("input_checksum", sa.String(64), nullable=False), sa.Column("output_formats", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("adapter", sa.String(80), nullable=False), sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error_detail", sa.JSON(), nullable=True), sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True), sa.ForeignKeyConstraint(["project_id"], ["projects.id"]))
    for column in ("project_id", "status"):
        op.create_index(f"ix_twin_conversion_jobs_{column}", "twin_conversion_jobs", [column])
    op.create_table("twin_telemetry_readings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("sensor_id", sa.String(64), nullable=False), sa.Column("twin_id", sa.String(96), nullable=False),
        sa.Column("value", sa.Float(), nullable=False), sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("quality", sa.String(20), nullable=False), sa.Column("sampled_at", sa.DateTime(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["sensor_id"], ["twin_sensors.id"]), sa.ForeignKeyConstraint(["twin_id"], ["twin_objects.id"]))
    for column in ("project_id", "sensor_id", "twin_id", "sampled_at"):
        op.create_index(f"ix_twin_telemetry_readings_{column}", "twin_telemetry_readings", [column])
    op.create_table("twin_copilot_runs",
        sa.Column("id", sa.String(96), primary_key=True), sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False), sa.Column("intent", sa.String(48), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False), sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["project_id"], ["projects.id"]))
    op.create_index("ix_twin_copilot_runs_project_id", "twin_copilot_runs", ["project_id"])


def downgrade() -> None:
    for table in ("twin_copilot_runs", "twin_telemetry_readings", "twin_conversion_jobs", "twin_model_versions", "twin_profiles"):
        op.drop_table(table)
