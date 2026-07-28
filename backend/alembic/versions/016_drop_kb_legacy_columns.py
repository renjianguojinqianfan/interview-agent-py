"""drop knowledge_bases legacy file-level columns

Revision ID: 016
Revises: 015
Create Date: 2026-07-28

Issue #59 contract 阶段：删除 knowledge_bases 表上已迁移到 knowledge_base_documents
的文件级列（file_hash, original_filename, file_size, content_type, storage_key,
storage_url, content_text, vector_job_id, vectorized_at）。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "016"
down_revision: str | Sequence[str] | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS: list[str] = [
    "file_hash",
    "original_filename",
    "file_size",
    "content_type",
    "storage_key",
    "storage_url",
    "content_text",
    "vector_job_id",
    "vectorized_at",
]


def upgrade() -> None:
    for col in _COLUMNS:
        op.drop_column("knowledge_bases", col)


def downgrade() -> None:
    # 反向恢复：NOT NULL 列需要 server_default
    op.add_column("knowledge_bases", sa.Column("vectorized_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("knowledge_bases", sa.Column("vector_job_id", sa.String(64), nullable=True))
    op.add_column("knowledge_bases", sa.Column("content_text", sa.Text(), nullable=True))
    op.add_column("knowledge_bases", sa.Column("storage_url", sa.String(1000), nullable=True))
    op.add_column("knowledge_bases", sa.Column("storage_key", sa.String(500), nullable=True))
    op.add_column("knowledge_bases", sa.Column("content_type", sa.String(200), nullable=True))
    op.add_column("knowledge_bases", sa.Column("file_size", sa.BigInteger(), nullable=True))
    # original_filename NOT NULL → 需要 server_default
    op.add_column(
        "knowledge_bases",
        sa.Column("original_filename", sa.String(500), nullable=False, server_default=""),
    )
    # file_hash NOT NULL → 需要 server_default
    op.add_column(
        "knowledge_bases",
        sa.Column("file_hash", sa.String(64), nullable=False, server_default=""),
    )
