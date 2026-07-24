"""create interview_sessions and interview_answers tables

Revision ID: 004
Revises: 003
Create Date: 2026-07-18

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004"
down_revision: str | Sequence[str] | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_sessions",
        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            primary_key=True,
        ),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=64), nullable=False, server_default=sa.text("'java-backend'")),
        sa.Column("difficulty", sa.String(length=16), nullable=False, server_default=sa.text("'mid'")),
        sa.Column(
            "resume_id",
            sa.BigInteger(),
            sa.ForeignKey("resumes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("total_questions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("current_question_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'CREATED'")),
        sa.Column("questions_json", sa.Text(), nullable=True),
        sa.Column("overall_score", sa.Integer(), nullable=True),
        sa.Column("overall_feedback", sa.Text(), nullable=True),
        sa.Column("strengths_json", sa.Text(), nullable=True),
        sa.Column("improvements_json", sa.Text(), nullable=True),
        sa.Column("reference_answers_json", sa.Text(), nullable=True),
        sa.Column("evaluate_status", sa.String(length=20), nullable=True),
        sa.Column("evaluate_error", sa.String(length=500), nullable=True),
        sa.Column("llm_provider", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("uq_interview_session_session_id", "interview_sessions", ["session_id"], unique=True)
    op.create_index("idx_interview_session_resume_created", "interview_sessions", ["resume_id", "created_at"])
    op.create_index(
        "idx_interview_session_resume_status_created",
        "interview_sessions",
        ["resume_id", "status", "created_at"],
    )
    op.create_index("idx_interview_session_skill_created", "interview_sessions", ["skill_id", "created_at"])

    op.create_table(
        "interview_answers",
        sa.Column(
            "id",
            sa.BigInteger(),
            autoincrement=True,
            primary_key=True,
        ),
        sa.Column(
            "session_id",
            sa.BigInteger(),
            sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_index", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("user_answer", sa.Text(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("reference_answer", sa.Text(), nullable=True),
        sa.Column("key_points_json", sa.Text(), nullable=True),
        sa.Column("answered_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("session_id", "question_index", name="uk_interview_answer_session_question"),
    )
    op.create_index(
        "idx_interview_answer_session_question",
        "interview_answers",
        ["session_id", "question_index"],
    )


def downgrade() -> None:
    op.drop_index("idx_interview_answer_session_question", table_name="interview_answers")
    op.drop_table("interview_answers")
    op.drop_index("idx_interview_session_skill_created", table_name="interview_sessions")
    op.drop_index(
        "idx_interview_session_resume_status_created",
        table_name="interview_sessions",
    )
    op.drop_index("idx_interview_session_resume_created", table_name="interview_sessions")
    op.drop_index("uq_interview_session_session_id", table_name="interview_sessions")
    op.drop_table("interview_sessions")
