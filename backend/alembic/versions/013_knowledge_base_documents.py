"""knowledge base multi-document: documents table + vector_store ownership columns

Revision ID: 013
Revises: 012
Create Date: 2026-07-26

知识库多文档 expand 阶段（ADR-0018，issue #52）：
1. knowledge_base_documents 新表——文件级字段从 knowledge_bases 拆出，
   (knowledge_base_id, file_hash) 复合唯一（同库去重、跨库允许）；
2. 存量搬迁——每个既有 knowledge_bases 行幂等生成一条 document（WHERE NOT EXISTS）；
3. vector_store 加 knowledge_base_id/document_id 实体列 + btree 复合索引，
   按 metadata->>'kb_id' 回填（迁移时每 KB 恰一 document，可直接 JOIN 回填 document_id）。

knowledge_bases 旧列全部保留（contract 阶段另行收敛）；downgrade 完整可回退。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "013"
down_revision: str | Sequence[str] | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. 文档表
    op.create_table(
        "knowledge_base_documents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "knowledge_base_id",
            sa.BigInteger(),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
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
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("vectorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("knowledge_base_id", "file_hash", name="uq_kb_document_kb_file_hash"),
        comment="知识库文档（一库多文档，ADR-0018）",
    )
    op.create_index("idx_kb_document_kb", "knowledge_base_documents", ["knowledge_base_id"])

    # 2. 存量搬迁：每个既有 KB 行生成一条 document（幂等）
    op.execute(
        """
        INSERT INTO knowledge_base_documents (
            knowledge_base_id, file_hash, original_filename, file_size, content_type,
            storage_key, storage_url, content_text, chunk_count, vector_status,
            vector_error, vector_job_id, uploaded_at, vectorized_at
        )
        SELECT kb.id, kb.file_hash, kb.original_filename, kb.file_size, kb.content_type,
               kb.storage_key, kb.storage_url, kb.content_text, kb.chunk_count, kb.vector_status,
               kb.vector_error, kb.vector_job_id, kb.uploaded_at, kb.vectorized_at
        FROM knowledge_bases kb
        WHERE NOT EXISTS (
            SELECT 1 FROM knowledge_base_documents d
            WHERE d.knowledge_base_id = kb.id AND d.file_hash = kb.file_hash
        )
        """
    )

    # 3. vector_store 归属实体列 + 回填 + 复合索引
    op.add_column("vector_store", sa.Column("knowledge_base_id", sa.BigInteger(), nullable=True))
    op.add_column("vector_store", sa.Column("document_id", sa.BigInteger(), nullable=True))
    op.execute(
        """
        UPDATE vector_store
        SET knowledge_base_id = (metadata->>'kb_id')::bigint
        WHERE knowledge_base_id IS NULL AND metadata ? 'kb_id'
        """
    )
    # 迁移时每 KB 恰有一条 document，JOIN 唯一
    op.execute(
        """
        UPDATE vector_store vs
        SET document_id = d.id
        FROM knowledge_base_documents d
        WHERE vs.document_id IS NULL AND vs.knowledge_base_id = d.knowledge_base_id
        """
    )
    op.create_index("idx_vector_store_kb_doc", "vector_store", ["knowledge_base_id", "document_id"])


def downgrade() -> None:
    op.drop_index("idx_vector_store_kb_doc", table_name="vector_store")
    op.drop_column("vector_store", "document_id")
    op.drop_column("vector_store", "knowledge_base_id")
    op.drop_index("idx_kb_document_kb", table_name="knowledge_base_documents")
    op.drop_table("knowledge_base_documents")
