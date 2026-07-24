from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.llm_provider import LlmProvider


class LlmProviderRepository:
    """LLM 供应商异步仓储。每个方法接收一个 AsyncSession，不在内部管理事务。"""

    async def save(self, session: AsyncSession, provider: LlmProvider) -> LlmProvider:
        session.add(provider)
        await session.flush()
        return provider

    async def get_by_id(self, session: AsyncSession, provider_id: int) -> LlmProvider | None:
        result = await session.execute(select(LlmProvider).where(LlmProvider.id == provider_id))
        return result.scalar_one_or_none()

    async def get_by_name(self, session: AsyncSession, provider_name: str) -> LlmProvider | None:
        result = await session.execute(select(LlmProvider).where(LlmProvider.provider_name == provider_name))
        return result.scalar_one_or_none()

    async def list_all(self, session: AsyncSession) -> list[LlmProvider]:
        result = await session.execute(select(LlmProvider).order_by(LlmProvider.id))
        return list(result.scalars().all())

    async def delete(self, session: AsyncSession, provider: LlmProvider) -> None:
        await session.delete(provider)

    async def exists_by_name(self, session: AsyncSession, provider_name: str) -> bool:
        result = await session.execute(
            select(func.count()).select_from(LlmProvider).where(LlmProvider.provider_name == provider_name)
        )
        return int(result.scalar() or 0) > 0
