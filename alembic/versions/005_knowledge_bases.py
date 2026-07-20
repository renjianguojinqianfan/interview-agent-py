"""create knowledge_bases table

Revision ID: 005
Revises: 004
Create Date: 2026-07-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "005"
down_revision: str | Sequence[str] | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            primary_key=True,
        ),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("content_type", sa.String(length=200), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("storage_url", sa.String(length=1000), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("vector_status", sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("vector_error", sa.String(length=500), nullable=True),
        sa.Column("vector_job_id", sa.String(length=64), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("vectorized_at", sa.DateTime(), nullable=True),
    )
    op.create_index("uq_knowledge_base_file_hash", "knowledge_bases", ["file_hash"], unique=True)
    op.create_index("idx_knowledge_base_uploaded_at", "knowledge_bases", ["uploaded_at"])


def downgrade() -> None:
    op.drop_index("idx_knowledge_base_uploaded_at", table_name="knowledge_bases")
    op.drop_index("uq_knowledge_base_file_hash", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
