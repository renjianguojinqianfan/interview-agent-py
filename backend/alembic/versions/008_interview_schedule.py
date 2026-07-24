"""create interview_schedule table

Revision ID: 008
Revises: 007
Create Date: 2026-07-21

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "008"
down_revision: str | Sequence[str] | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_schedule",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("position", sa.String(length=200), nullable=False),
        sa.Column("interview_time", sa.DateTime(), nullable=False),
        sa.Column("interview_type", sa.String(length=20), nullable=True),
        sa.Column("meeting_link", sa.Text(), nullable=True),
        sa.Column("round_number", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("interviewer", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_interview_schedule_status",
        "interview_schedule",
        ["status"],
    )
    op.create_index(
        "ix_interview_schedule_interview_time",
        "interview_schedule",
        ["interview_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_interview_schedule_interview_time", table_name="interview_schedule")
    op.drop_index("ix_interview_schedule_status", table_name="interview_schedule")
    op.drop_table("interview_schedule")
