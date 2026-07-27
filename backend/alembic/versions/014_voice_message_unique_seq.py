"""voice message unique (session_id, sequence_num) constraint

Revision ID: 014
Revises: 013
Create Date: 2026-07-27

#61（#57 review 遗留）：并发 WS 连接的 check-then-insert 与 _persist_turn 的 count+1
取 seq 均非原子，可产生同 session 同 seq 脏行。DB 层加唯一约束兜底：并发插入时
后到者违约、被应用侧最佳努力 except 吞掉，天然幂等。

upgrade 先去重（同组保留最小 id，既有部署可能已有历史脏行；开发库已核查无脏行，
此步为幂等防线）再建约束。downgrade 仅撤约束——去重删除不可逆。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "014"
down_revision: str | Sequence[str] | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. 存量脏行去重：同 (session_id, sequence_num) 组保留最小 id
    op.execute(
        sa.text(
            "DELETE FROM voice_interview_messages a "
            "USING voice_interview_messages b "
            "WHERE a.session_id = b.session_id "
            "AND a.sequence_num = b.sequence_num "
            "AND a.id > b.id"
        )
    )
    # 2. 唯一约束兜底（命名对齐 009 的 uk_voice_interview_evaluation_session 惯例）
    op.create_unique_constraint(
        "uk_voice_interview_message_session_seq",
        "voice_interview_messages",
        ["session_id", "sequence_num"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uk_voice_interview_message_session_seq",
        "voice_interview_messages",
        type_="unique",
    )
