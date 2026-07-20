"""create llm_global_setting and voice_config tables, add unique on provider_name

Revision ID: 007
Revises: 006
Create Date: 2026-07-20

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "007"
down_revision: str | Sequence[str] | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_global_setting",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("default_chat_provider_id", sa.BigInteger(), nullable=False),
        sa.Column("default_embedding_provider_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "voice_config",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "asr_url",
            sa.String(length=500),
            nullable=False,
            server_default=sa.text("'wss://dashscope.aliyuncs.com/api-ws/v1/realtime'"),
        ),
        sa.Column(
            "asr_model", sa.String(length=100), nullable=False, server_default=sa.text("'qwen3-asr-flash-realtime'")
        ),
        sa.Column("asr_api_key", sa.String(length=1000), nullable=False, server_default=sa.text("''")),
        sa.Column("asr_language", sa.String(length=20), nullable=False, server_default=sa.text("'zh'")),
        sa.Column("asr_format", sa.String(length=20), nullable=False, server_default=sa.text("'pcm'")),
        sa.Column("asr_sample_rate", sa.Integer(), nullable=False, server_default=sa.text("16000")),
        sa.Column("asr_enable_turn_detection", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "asr_turn_detection_type", sa.String(length=50), nullable=False, server_default=sa.text("'server_vad'")
        ),
        sa.Column("asr_turn_detection_threshold", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column(
            "asr_turn_detection_silence_duration_ms", sa.Integer(), nullable=False, server_default=sa.text("2000")
        ),
        sa.Column(
            "tts_model", sa.String(length=100), nullable=False, server_default=sa.text("'qwen3-tts-flash-realtime'")
        ),
        sa.Column("tts_api_key", sa.String(length=1000), nullable=False, server_default=sa.text("''")),
        sa.Column("tts_voice", sa.String(length=100), nullable=False, server_default=sa.text("'Cherry'")),
        sa.Column("tts_format", sa.String(length=20), nullable=False, server_default=sa.text("'pcm'")),
        sa.Column("tts_sample_rate", sa.Integer(), nullable=False, server_default=sa.text("24000")),
        sa.Column("tts_mode", sa.String(length=20), nullable=False, server_default=sa.text("'commit'")),
        sa.Column("tts_language_type", sa.String(length=50), nullable=False, server_default=sa.text("'Chinese'")),
        sa.Column("tts_speech_rate", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("tts_volume", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )

    op.create_unique_constraint(
        "uq_llm_provider_config_provider_name",
        "llm_provider_config",
        ["provider_name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_llm_provider_config_provider_name", "llm_provider_config", type_="unique")
    op.drop_table("voice_config")
    op.drop_table("llm_global_setting")
