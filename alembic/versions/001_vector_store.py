"""create vector_store table with pgvector

Revision ID: 001
Revises:
Create Date: 2026-07-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "vector_store",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    op.execute("ALTER TABLE vector_store ADD COLUMN embedding vector(1024)")

    op.execute("CREATE INDEX vector_store_embedding_hnsw_idx ON vector_store USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    op.drop_index("vector_store_embedding_hnsw_idx", table_name="vector_store")
    op.drop_table("vector_store")
