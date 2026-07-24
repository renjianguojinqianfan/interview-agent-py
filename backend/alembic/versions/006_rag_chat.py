"""create rag_chat_sessions and rag_chat_messages tables

Revision ID: 006
Revises: 005
Create Date: 2026-07-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "006"
down_revision: str | Sequence[str] | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rag_chat_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_base_ids_json", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'ACTIVE'")),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("uq_rag_chat_session_session_id", "rag_chat_sessions", ["session_id"], unique=True)
    op.create_index("idx_rag_chat_session_pinned_updated", "rag_chat_sessions", ["pinned", "updated_at"])

    op.create_table(
        "rag_chat_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "session_id",
            sa.BigInteger(),
            sa.ForeignKey("rag_chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("sources_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("idx_rag_chat_message_session_created", "rag_chat_messages", ["session_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_rag_chat_message_session_created", table_name="rag_chat_messages")
    op.drop_table("rag_chat_messages")
    op.drop_index("idx_rag_chat_session_pinned_updated", table_name="rag_chat_sessions")
    op.drop_index("uq_rag_chat_session_session_id", table_name="rag_chat_sessions")
    op.drop_table("rag_chat_sessions")
