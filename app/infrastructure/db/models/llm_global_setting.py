from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class LlmGlobalSetting(Base):
    """LLM 全局设置（单例表，id 固定为 1）。"""

    __tablename__ = "llm_global_setting"

    SINGLETON_ID = 1

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    default_chat_provider_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    default_embedding_provider_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
