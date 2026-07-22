"""add knowledge_bases metadata columns (name/category/counts/last_accessed_at)

Revision ID: 011
Revises: 010
Create Date: 2026-07-22

对齐复用的 Java 前端契约（ADR-0001）：KnowledgeBaseListItemDTO 需要
name / category / accessCount / questionCount / lastAccessedAt 字段。
追加式加列（ADR-0002），不改历史迁移。last_accessed_at 直接建为 timestamptz
（ADR-0013，post-010 约定：新增 datetime 列统一 timezone-aware）。

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "011"
down_revision: str | Sequence[str] | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("knowledge_bases", sa.Column("name", sa.String(length=500), nullable=True))
    op.add_column("knowledge_bases", sa.Column("category", sa.String(length=100), nullable=True))
    op.add_column(
        "knowledge_bases",
        sa.Column("access_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("question_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # 既有行 name 回填为原始文件名（空库无副作用；有数据时保证展示名非空可用）
    op.execute("UPDATE knowledge_bases SET name = original_filename WHERE name IS NULL")
    op.create_index("idx_knowledge_base_category", "knowledge_bases", ["category"])


def downgrade() -> None:
    op.drop_index("idx_knowledge_base_category", table_name="knowledge_bases")
    op.drop_column("knowledge_bases", "last_accessed_at")
    op.drop_column("knowledge_bases", "question_count")
    op.drop_column("knowledge_bases", "access_count")
    op.drop_column("knowledge_bases", "category")
    op.drop_column("knowledge_bases", "name")
