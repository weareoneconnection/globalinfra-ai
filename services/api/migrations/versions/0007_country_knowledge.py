"""country packs and governed knowledge fabric

Revision ID: 0007
Revises: 0006
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "country_packs",
        sa.Column("code", sa.String(8), primary_key=True),
        sa.Column("name", sa.JSON(), nullable=False),
        sa.Column("region", sa.String(32), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("default_locale", sa.String(20), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("units", sa.String(20), nullable=False),
        sa.Column("supported_domains", sa.JSON(), nullable=False),
        sa.Column("authorities", sa.JSON(), nullable=False),
        sa.Column("permit_catalog", sa.JSON(), nullable=False),
        sa.Column("compliance_topics", sa.JSON(), nullable=False),
        sa.Column("glossary", sa.JSON(), nullable=False),
        sa.Column("data_policy", sa.JSON(), nullable=False),
        sa.Column("approval_policy", sa.JSON(), nullable=False),
        sa.Column("source_registry", sa.JSON(), nullable=False),
        sa.Column("disclaimer", sa.JSON(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_country_packs_region", "country_packs", ["region"])
    op.create_index("ix_country_packs_status", "country_packs", ["status"])
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.add_column(sa.Column("country_code", sa.String(8), nullable=True))
        batch.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("document_type", sa.String(40), nullable=False, server_default="GUIDANCE"))
        batch.add_column(sa.Column("authority", sa.String(160), nullable=True))
        batch.add_column(sa.Column("version", sa.String(64), nullable=False, server_default="1.0"))
        batch.add_column(sa.Column("status", sa.String(32), nullable=False, server_default="CURRENT"))
        batch.add_column(sa.Column("effective_date", sa.String(32), nullable=True))
        batch.add_column(sa.Column("review_due", sa.String(32), nullable=True))
        batch.add_column(sa.Column("source_url", sa.String(500), nullable=True))
        batch.add_column(sa.Column("content_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("lifecycle_stages", sa.JSON(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("confidentiality", sa.String(24), nullable=False, server_default="PUBLIC"))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        batch.create_foreign_key("fk_knowledge_project", "projects", ["project_id"], ["id"])
    for column in ("country_code", "project_id", "document_type", "status", "content_hash"):
        op.create_index(f"ix_knowledge_documents_{column}", "knowledge_documents", [column])


def downgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.drop_constraint("fk_knowledge_project", type_="foreignkey")
        for column in ("country_code", "project_id", "document_type", "authority", "version", "status", "effective_date", "review_due", "source_url", "content_hash", "tags", "lifecycle_stages", "confidentiality", "updated_at"):
            batch.drop_column(column)
    op.drop_table("country_packs")
