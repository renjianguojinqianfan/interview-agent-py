"""drop knowledge_bases.file_hash unique constraint

Revision ID: 015
Revises: 014
Create Date: 2026-07-28

Issue #67 前置：移除 file_hash 全局唯一约束，为跨知识库同文件上传铺路。
原始约束由 005_knowledge_bases 以唯一索引 uq_knowledge_base_file_hash 创建。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "015"
down_revision: str | Sequence[str] | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_knowledge_base_file_hash", table_name="knowledge_bases")


def downgrade() -> None:
    op.create_index("uq_knowledge_base_file_hash", "knowledge_bases", ["file_hash"], unique=True)
