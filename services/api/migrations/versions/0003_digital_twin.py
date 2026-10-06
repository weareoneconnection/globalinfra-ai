"""full-lifecycle digital twin foundation (V2.0)

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("twin_objects",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("parent_id", sa.String(96), sa.ForeignKey("twin_objects.id"), nullable=True),
        sa.Column("object_type", sa.String(40), nullable=False), sa.Column("name", sa.JSON(), nullable=False),
        sa.Column("lifecycle_stage", sa.String(40), nullable=False), sa.Column("status", sa.String(48), nullable=False),
        sa.Column("health_score", sa.Float(), nullable=False), sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("geometry_ref", sa.String(255), nullable=True), sa.Column("ifc_guid", sa.String(64), nullable=True),
        sa.Column("location", sa.JSON(), nullable=False), sa.Column("properties", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    for column in ("project_id", "parent_id", "object_type", "lifecycle_stage", "status", "ifc_guid"):
        op.create_index(f"ix_twin_objects_{column}", "twin_objects", [column])

    op.create_table("twin_relations", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(96), sa.ForeignKey("twin_objects.id"), nullable=False),
        sa.Column("target_id", sa.String(96), sa.ForeignKey("twin_objects.id"), nullable=False),
        sa.Column("relation_type", sa.String(40), nullable=False), sa.Column("metadata_json", sa.JSON(), nullable=False))
    for column in ("source_id", "target_id", "relation_type"):
        op.create_index(f"ix_twin_relations_{column}", "twin_relations", [column])

    op.create_table("twin_state_history", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("twin_id", sa.String(96), sa.ForeignKey("twin_objects.id"), nullable=False),
        sa.Column("previous_status", sa.String(48), nullable=False), sa.Column("status", sa.String(48), nullable=False),
        sa.Column("source_system", sa.String(64), nullable=False), sa.Column("evidence_ref", sa.String(255), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False), sa.Column("effective_at", sa.DateTime(), nullable=False))
    for column in ("twin_id", "status", "effective_at"):
        op.create_index(f"ix_twin_state_history_{column}", "twin_state_history", [column])

    op.create_table("twin_events", sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("twin_id", sa.String(96), sa.ForeignKey("twin_objects.id"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False), sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("title", sa.JSON(), nullable=False), sa.Column("domain", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False), sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False))
    for column in ("twin_id", "event_type", "severity", "occurred_at"):
        op.create_index(f"ix_twin_events_{column}", "twin_events", [column])

    op.create_table("twin_schedule_links", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("twin_id", sa.String(96), sa.ForeignKey("twin_objects.id"), nullable=False),
        sa.Column("wbs_code", sa.String(64), nullable=False), sa.Column("activity_id", sa.String(64), nullable=False),
        sa.Column("planned_progress", sa.Float(), nullable=False), sa.Column("actual_progress", sa.Float(), nullable=False),
        sa.Column("schedule_variance_days", sa.Integer(), nullable=False), sa.Column("cost_code", sa.String(64), nullable=False),
        sa.Column("budget", sa.Float(), nullable=False), sa.Column("forecast", sa.Float(), nullable=False))
    for column in ("twin_id", "wbs_code", "activity_id"):
        op.create_index(f"ix_twin_schedule_links_{column}", "twin_schedule_links", [column])

    op.create_table("twin_sensors", sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("twin_id", sa.String(96), sa.ForeignKey("twin_objects.id"), nullable=False),
        sa.Column("sensor_type", sa.String(40), nullable=False), sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("threshold_warning", sa.Float(), nullable=False),
        sa.Column("threshold_critical", sa.Float(), nullable=False), sa.Column("latest_value", sa.Float(), nullable=False),
        sa.Column("sampled_at", sa.DateTime(), nullable=False))
    op.create_index("ix_twin_sensors_twin_id", "twin_sensors", ["twin_id"])

    op.create_table("commissioning_items", sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("twin_id", sa.String(96), sa.ForeignKey("twin_objects.id"), nullable=False),
        sa.Column("system", sa.JSON(), nullable=False), sa.Column("test_pack", sa.String(80), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False), sa.Column("punch_open", sa.Integer(), nullable=False),
        sa.Column("document_completeness", sa.Float(), nullable=False), sa.Column("readiness", sa.Float(), nullable=False))
    op.create_index("ix_commissioning_items_twin_id", "commissioning_items", ["twin_id"])
    op.create_index("ix_commissioning_items_stage", "commissioning_items", ["stage"])

    op.create_table("maintenance_records", sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("twin_id", sa.String(96), sa.ForeignKey("twin_objects.id"), nullable=False),
        sa.Column("work_type", sa.String(40), nullable=False), sa.Column("status", sa.String(40), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False), sa.Column("description", sa.JSON(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False))
    op.create_index("ix_maintenance_records_twin_id", "maintenance_records", ["twin_id"])
    op.create_index("ix_maintenance_records_status", "maintenance_records", ["status"])

    op.create_table("twin_scenarios", sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.JSON(), nullable=False), sa.Column("scenario_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False), sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_twin_scenarios_project_id", "twin_scenarios", ["project_id"])


def downgrade() -> None:
    for table in ("twin_scenarios", "maintenance_records", "commissioning_items", "twin_sensors",
                  "twin_schedule_links", "twin_events", "twin_state_history", "twin_relations", "twin_objects"):
        op.drop_table(table)
