"""migrate all datetime columns to timezone-aware (timestamptz)

Revision ID: 010
Revises: 009
Create Date: 2026-07-22

ADR-0013：内部统一 aware UTC。全表 DateTime 列由 naive (timestamp) 迁移到
timezone=True (timestamptz)，既有 naive 值按 UTC 解释（AT TIME ZONE 'UTC'）。
全新空库（ADR-0002）无生产数据，本迁移对空表为纯 schema 变更。

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "010"
down_revision: str | Sequence[str] | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 全部 datetime 列 (表名, 列名)，与 app/infrastructure/db/models 一一对应。
_DATETIME_COLUMNS: list[tuple[str, str]] = [
    ("resumes", "uploaded_at"),
    ("resumes", "last_accessed_at"),
    ("resume_analyses", "analyzed_at"),
    ("interview_sessions", "created_at"),
    ("interview_sessions", "completed_at"),
    ("interview_answers", "answered_at"),
    ("knowledge_bases", "uploaded_at"),
    ("knowledge_bases", "vectorized_at"),
    ("rag_chat_sessions", "created_at"),
    ("rag_chat_sessions", "updated_at"),
    ("rag_chat_messages", "created_at"),
    ("llm_provider_config", "created_at"),
    ("llm_provider_config", "updated_at"),
    ("llm_global_setting", "created_at"),
    ("llm_global_setting", "updated_at"),
    ("voice_config", "created_at"),
    ("voice_config", "updated_at"),
    ("interview_schedule", "interview_time"),
    ("interview_schedule", "created_at"),
    ("interview_schedule", "updated_at"),
    ("voice_interview_sessions", "start_time"),
    ("voice_interview_sessions", "end_time"),
    ("voice_interview_sessions", "created_at"),
    ("voice_interview_sessions", "updated_at"),
    ("voice_interview_sessions", "paused_at"),
    ("voice_interview_sessions", "resumed_at"),
    ("voice_interview_messages", "timestamp"),
    ("voice_interview_messages", "created_at"),
    ("voice_interview_evaluations", "interview_date"),
    ("voice_interview_evaluations", "created_at"),
]


def upgrade() -> None:
    # naive -> aware：既有 naive 值按 UTC 解释后转 timestamptz。
    for table, column in _DATETIME_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(timezone=True),
            existing_type=sa.DateTime(),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    # aware -> naive：取 UTC wall-clock 落回 timestamp（无时区）。
    for table, column in _DATETIME_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.DateTime(),
            existing_type=sa.DateTime(timezone=True),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )
