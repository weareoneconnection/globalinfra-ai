"""add evidence-grounded drawing intelligence and draft model runs

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drawing_documents",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(16), nullable=False),
        sa.Column("content_type", sa.String(160), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_ref", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("data_classification", sa.String(24), nullable=False),
        sa.Column("discipline", sa.String(64), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("drawing_number", sa.String(96), nullable=True),
        sa.Column("revision", sa.String(32), nullable=True),
        sa.Column("scale", sa.String(32), nullable=True),
        sa.Column("unit", sa.String(24), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("original_content", sa.LargeBinary(), nullable=False),
        sa.Column("uploaded_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for name, columns in (
        ("ix_drawing_documents_organization_id", ["organization_id"]),
        ("ix_drawing_documents_project_id", ["project_id"]),
        ("ix_drawing_documents_file_type", ["file_type"]),
        ("ix_drawing_documents_sha256", ["sha256"]),
        ("ix_drawing_documents_status", ["status"]),
        ("ix_drawing_documents_data_classification", ["data_classification"]),
        ("ix_drawing_documents_discipline", ["discipline"]),
        ("ix_drawing_documents_drawing_number", ["drawing_number"]),
        ("ix_drawing_documents_created_at", ["created_at"]),
    ):
        op.create_index(name, "drawing_documents", columns)

    op.create_table(
        "drawing_sheets",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("drawing_id", sa.String(96), sa.ForeignKey("drawing_documents.id"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("height", sa.Float(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("vector_primitive_count", sa.Integer(), nullable=False),
        sa.Column("parse_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("drawing_id", "page_number"),
    )
    op.create_index("ix_drawing_sheets_drawing_id", "drawing_sheets", ["drawing_id"])
    op.create_index("ix_drawing_sheets_parse_status", "drawing_sheets", ["parse_status"])

    op.create_table(
        "drawing_elements",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("drawing_id", sa.String(96), sa.ForeignKey("drawing_documents.id"), nullable=False),
        sa.Column("sheet_id", sa.String(96), sa.ForeignKey("drawing_sheets.id"), nullable=False),
        sa.Column("element_type", sa.String(48), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(24), nullable=True),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("extraction_method", sa.String(48), nullable=False),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("properties", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for name, columns in (
        ("ix_drawing_elements_drawing_id", ["drawing_id"]),
        ("ix_drawing_elements_sheet_id", ["sheet_id"]),
        ("ix_drawing_elements_element_type", ["element_type"]),
        ("ix_drawing_elements_review_status", ["review_status"]),
    ):
        op.create_index(name, "drawing_elements", columns)

    op.create_table(
        "drawing_analysis_runs",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("drawing_id", sa.String(96), sa.ForeignKey("drawing_documents.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("model_ready", sa.Boolean(), nullable=False),
        sa.Column("blockers", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    for name, columns in (
        ("ix_drawing_analysis_runs_drawing_id", ["drawing_id"]),
        ("ix_drawing_analysis_runs_status", ["status"]),
        ("ix_drawing_analysis_runs_source_sha256", ["source_sha256"]),
        ("ix_drawing_analysis_runs_model_ready", ["model_ready"]),
    ):
        op.create_index(name, "drawing_analysis_runs", columns)

    op.create_table(
        "drawing_model_runs",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("drawing_document_id", sa.String(96), sa.ForeignKey("drawing_documents.id"), nullable=False),
        sa.Column("organization_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("validation", sa.JSON(), nullable=False),
        sa.Column("gltf_content", sa.LargeBinary(), nullable=True),
        sa.Column("ifc_content", sa.LargeBinary(), nullable=True),
        sa.Column("gltf_digest", sa.String(64), nullable=True),
        sa.Column("ifc_digest", sa.String(64), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for name, columns in (
        ("ix_drawing_model_runs_drawing_document_id", ["drawing_document_id"]),
        ("ix_drawing_model_runs_organization_id", ["organization_id"]),
        ("ix_drawing_model_runs_project_id", ["project_id"]),
        ("ix_drawing_model_runs_status", ["status"]),
        ("ix_drawing_model_runs_created_at", ["created_at"]),
    ):
        op.create_index(name, "drawing_model_runs", columns)


def downgrade() -> None:
    op.drop_table("drawing_model_runs")
    op.drop_table("drawing_analysis_runs")
    op.drop_table("drawing_elements")
    op.drop_table("drawing_sheets")
    op.drop_table("drawing_documents")
