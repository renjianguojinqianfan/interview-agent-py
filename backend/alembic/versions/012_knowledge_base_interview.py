"""knowledge base interview schema: question bank table + gen status columns + session source columns

Revision ID: 012
Revises: 011
Create Date: 2026-07-26

知识库面试功能域 schema 基座（Java 8c80a19..646b23e 迁移，issue #41）：
1. knowledge_base_questions 新表——AI 生成/手动维护的题库（题干/方向/难度/参考答案/
   评分要点/追问池），列型对齐 Java V1__init_schema.sql；
2. knowledge_bases 加 question_gen_* 8 列——题目异步生成状态机（NONE/QUEUED/
   PROCESSING/COMPLETED/FAILED）与恢复快照；
3. interview_sessions 加 source_type/knowledge_base_id/interview_category——
   标注会话来源（NORMAL 普通面试 / KNOWLEDGE_BASE 知识库面试）。

时间列一律 timestamptz（ADR-0013，不照搬 Java naive TIMESTAMP(6)）。
knowledge_base_id 外键 ON DELETE CASCADE（沿用本仓库 interview_answers 惯例，
偏离 Java 默认 RESTRICT——Java 删除服务未清理题目，属其侧缺陷，不照搬）。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "012"
down_revision: str | Sequence[str] | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. 题库表
    op.create_table(
        "knowledge_base_questions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "knowledge_base_id",
            sa.BigInteger(),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("skill_id", sa.String(length=64), nullable=False, server_default=sa.text("'knowledge-base'")),
        sa.Column("difficulty", sa.String(length=16), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("topic_summary", sa.String(length=300), nullable=True),
        sa.Column("reference_answer", sa.Text(), nullable=True),
        sa.Column("key_points_json", sa.Text(), nullable=True),
        sa.Column("scoring_rubric", sa.Text(), nullable=True),
        sa.Column("follow_ups_json", sa.Text(), nullable=True),
        sa.Column("source_context", sa.Text(), nullable=True),
        sa.Column("kb_content_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'ARCHIVED', 'STALE')",
            name="knowledge_base_questions_status_check",
        ),
        comment="知识库面试题库",
    )
    op.create_index("idx_kb_question_kb_status", "knowledge_base_questions", ["knowledge_base_id", "status"])
    op.create_index("idx_kb_question_skill_difficulty", "knowledge_base_questions", ["skill_id", "difficulty"])

    # 2. 知识库题目生成状态列族
    op.add_column(
        "knowledge_bases",
        sa.Column("question_gen_status", sa.String(length=20), nullable=False, server_default=sa.text("'NONE'")),
    )
    op.add_column("knowledge_bases", sa.Column("question_gen_error", sa.String(length=500), nullable=True))
    op.add_column("knowledge_bases", sa.Column("question_gen_task_id", sa.String(length=36), nullable=True))
    op.add_column("knowledge_bases", sa.Column("question_gen_config", sa.Text(), nullable=True))
    op.add_column("knowledge_bases", sa.Column("question_gen_message", sa.String(length=500), nullable=True))
    op.add_column(
        "knowledge_bases",
        sa.Column("question_gen_saved_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("question_gen_skipped_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("knowledge_bases", sa.Column("question_gen_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "knowledge_bases_question_gen_status_check",
        "knowledge_bases",
        "question_gen_status IN ('NONE', 'QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED')",
    )
    op.create_index(
        "idx_kb_question_gen_status_updated",
        "knowledge_bases",
        ["question_gen_status", "question_gen_updated_at"],
    )

    # 3. 面试会话来源标注（knowledge_base_id 照搬 Java 裸列无外键：删库后会话保留历史可查）
    op.add_column(
        "interview_sessions",
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default=sa.text("'NORMAL'")),
    )
    op.add_column("interview_sessions", sa.Column("knowledge_base_id", sa.BigInteger(), nullable=True))
    op.add_column("interview_sessions", sa.Column("interview_category", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("interview_sessions", "interview_category")
    op.drop_column("interview_sessions", "knowledge_base_id")
    op.drop_column("interview_sessions", "source_type")

    op.drop_index("idx_kb_question_gen_status_updated", table_name="knowledge_bases")
    op.drop_constraint("knowledge_bases_question_gen_status_check", "knowledge_bases", type_="check")
    op.drop_column("knowledge_bases", "question_gen_updated_at")
    op.drop_column("knowledge_bases", "question_gen_skipped_count")
    op.drop_column("knowledge_bases", "question_gen_saved_count")
    op.drop_column("knowledge_bases", "question_gen_message")
    op.drop_column("knowledge_bases", "question_gen_config")
    op.drop_column("knowledge_bases", "question_gen_task_id")
    op.drop_column("knowledge_bases", "question_gen_error")
    op.drop_column("knowledge_bases", "question_gen_status")

    op.drop_index("idx_kb_question_skill_difficulty", table_name="knowledge_base_questions")
    op.drop_index("idx_kb_question_kb_status", table_name="knowledge_base_questions")
    op.drop_table("knowledge_base_questions")
