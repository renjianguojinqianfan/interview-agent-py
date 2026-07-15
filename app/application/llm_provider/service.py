import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db.models.llm_provider import LlmProvider

logger = logging.getLogger(__name__)


async def seed_default_provider(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await session.execute(select(LlmProvider))
        if result.scalars().first() is None:
            session.add(
                LlmProvider(
                    provider_name="dashscope",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    api_key="",
                    model="qwen3.5-flash",
                    embedding_model="text-embedding-v3",
                    embedding_dimensions=1024,
                    supports_embedding=True,
                    is_default=True,
                )
            )
            await session.commit()
            logger.info("Seeded default dashscope provider")
