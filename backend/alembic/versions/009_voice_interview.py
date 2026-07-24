"""create voice_interview tables

Revision ID: 009
Revises: 008
Create Date: 2026-07-21

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "009"
down_revision: str | Sequence[str] | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voice_interview_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False, server_default=sa.text("'default'")),
        sa.Column("role_type", sa.String(length=64), nullable=False),
        sa.Column("skill_id", sa.String(length=64), nullable=False, server_default=sa.text("'java-backend'")),
        sa.Column("difficulty", sa.String(length=16), nullable=False, server_default=sa.text("'mid'")),
        sa.Column("custom_jd_text", sa.Text(), nullable=True),
        sa.Column(
            "resume_id",
            sa.BigInteger(),
            sa.ForeignKey("resumes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("intro_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("tech_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("project_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("hr_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("llm_provider", sa.String(length=50), nullable=True),
        sa.Column("current_phase", sa.String(length=20), nullable=False, server_default=sa.text("'INTRO'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'IN_PROGRESS'")),
        sa.Column("planned_duration", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("actual_duration", sa.Integer(), nullable=True),
        sa.Column("start_time", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("paused_at", sa.DateTime(), nullable=True),
        sa.Column("resumed_at", sa.DateTime(), nullable=True),
        sa.Column("evaluate_status", sa.String(length=20), nullable=True),
        sa.Column("evaluate_error", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_voice_interview_sessions_user_id",
        "voice_interview_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_voice_interview_sessions_status_updated_at",
        "voice_interview_sessions",
        ["status", "updated_at"],
    )
    op.create_index(
        "ix_voice_interview_sessions_evaluate_status",
        "voice_interview_sessions",
        ["evaluate_status"],
    )

    op.create_table(
        "voice_interview_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "session_id",
            sa.BigInteger(),
            sa.ForeignKey("voice_interview_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_type", sa.String(length=20), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("user_recognized_text", sa.Text(), nullable=True),
        sa.Column("ai_generated_text", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("sequence_num", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_voice_interview_messages_session_id",
        "voice_interview_messages",
        ["session_id"],
    )

    op.create_table(
        "voice_interview_evaluations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "session_id",
            sa.BigInteger(),
            sa.ForeignKey("voice_interview_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("overall_score", sa.Integer(), nullable=True),
        sa.Column("overall_feedback", sa.Text(), nullable=True),
        sa.Column("question_evaluations_json", sa.Text(), nullable=True),
        sa.Column("strengths_json", sa.Text(), nullable=True),
        sa.Column("improvements_json", sa.Text(), nullable=True),
        sa.Column("reference_answers_json", sa.Text(), nullable=True),
        sa.Column("interviewer_role", sa.String(length=64), nullable=True),
        sa.Column("interview_date", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uk_voice_interview_evaluation_session"),
    )


def downgrade() -> None:
    op.drop_table("voice_interview_evaluations")
    op.drop_index("ix_voice_interview_messages_session_id", table_name="voice_interview_messages")
    op.drop_table("voice_interview_messages")
    op.drop_index("ix_voice_interview_sessions_evaluate_status", table_name="voice_interview_sessions")
    op.drop_index("ix_voice_interview_sessions_status_updated_at", table_name="voice_interview_sessions")
    op.drop_index("ix_voice_interview_sessions_user_id", table_name="voice_interview_sessions")
    op.drop_table("voice_interview_sessions")
