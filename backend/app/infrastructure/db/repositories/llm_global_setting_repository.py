from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.llm_global_setting import LlmGlobalSetting


class LlmGlobalSettingRepository:
    """LLM 全局设置异步仓储（单例表）。每个方法接收一个 AsyncSession，不在内部管理事务。"""

    async def get_singleton(self, session: AsyncSession) -> LlmGlobalSetting | None:
        result = await session.execute(
            select(LlmGlobalSetting).where(LlmGlobalSetting.id == LlmGlobalSetting.SINGLETON_ID)
        )
        return result.scalar_one_or_none()

    async def save(self, session: AsyncSession, setting: LlmGlobalSetting) -> LlmGlobalSetting:
        session.add(setting)
        await session.flush()
        return setting
