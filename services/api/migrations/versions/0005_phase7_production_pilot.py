"""phase 7 production-pilot operating plane

Revision ID: 0005
Revises: 0004
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "identities",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False, unique=True),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("project_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
    )
    op.create_index("ix_identities_organization_id", "identities", ["organization_id"])
    op.create_index("ix_identities_subject", "identities", ["subject"], unique=True)
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(160), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(160), nullable=True),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
    )
    for column in ("organization_id", "actor_id", "request_id", "action", "resource_type", "outcome", "occurred_at"):
        op.create_index(f"ix_audit_events_{column}", "audit_events", [column])
    op.create_table(
        "field_observations",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("client_id", sa.String(96), nullable=False, unique=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("twin_id", sa.String(96), nullable=True),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.JSON(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("reporter_id", sa.String(255), nullable=False),
        sa.Column("sync_status", sa.String(24), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["twin_id"], ["twin_objects.id"]),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
    )
    for column in ("client_id", "organization_id", "project_id", "twin_id", "event_type", "severity", "reporter_id", "sync_status", "case_id"):
        op.create_index(f"ix_field_observations_{column}", "field_observations", [column], unique=column == "client_id")
    op.create_table(
        "twin_sources",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("uri", sa.String(500), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("coordinate_reference_system", sa.String(80), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    for column in ("organization_id", "project_id", "source_type", "status"):
        op.create_index(f"ix_twin_sources_{column}", "twin_sources", [column])
    op.create_table(
        "connectors",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("connector_type", sa.String(48), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    for column in ("organization_id", "project_id", "connector_type", "status"):
        op.create_index(f"ix_connectors_{column}", "connectors", [column])
    op.create_table(
        "connector_sync_runs",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("connector_id", sa.String(96), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("cursor", sa.String(255), nullable=True),
        sa.Column("records_read", sa.Integer(), nullable=False),
        sa.Column("records_written", sa.Integer(), nullable=False),
        sa.Column("records_rejected", sa.Integer(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.id"]),
    )
    op.create_index("ix_connector_sync_runs_connector_id", "connector_sync_runs", ["connector_id"])
    op.create_index("ix_connector_sync_runs_status", "connector_sync_runs", ["status"])
    op.create_table(
        "ai_quality_runs",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("suite", sa.String(80), nullable=False),
        sa.Column("model_provider", sa.String(48), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("thresholds", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("dataset_version", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("organization_id", "suite", "status"):
        op.create_index(f"ix_ai_quality_runs_{column}", "ai_quality_runs", [column])


def downgrade() -> None:
    for table in (
        "ai_quality_runs", "connector_sync_runs", "connectors", "twin_sources",
        "field_observations", "audit_events", "identities", "organizations",
    ):
        op.drop_table(table)
