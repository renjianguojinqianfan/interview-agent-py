"""create resumes and resume_analyses tables

Revision ID: 002
Revises: 001
Create Date: 2026-07-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "002"
down_revision: str | Sequence[str] | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resumes",
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
        sa.Column("resume_text", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("analyze_status", sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("analyze_error", sa.String(length=500), nullable=True),
    )
    op.create_index("idx_resume_hash", "resumes", ["file_hash"], unique=True)

    op.create_table(
        "resume_analyses",
        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            primary_key=True,
        ),
        sa.Column(
            "resume_id",
            sa.BigInteger(),
            sa.ForeignKey("resumes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("overall_score", sa.Integer(), nullable=True),
        sa.Column("content_score", sa.Integer(), nullable=True),
        sa.Column("structure_score", sa.Integer(), nullable=True),
        sa.Column("skill_match_score", sa.Integer(), nullable=True),
        sa.Column("expression_score", sa.Integer(), nullable=True),
        sa.Column("project_score", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("strengths_json", sa.Text(), nullable=True),
        sa.Column("suggestions_json", sa.Text(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("resume_analyses")
    op.drop_index("idx_resume_hash", table_name="resumes")
    op.drop_table("resumes")
