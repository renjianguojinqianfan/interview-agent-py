from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models.voice_config import VoiceConfig


class VoiceConfigRepository:
    """语音服务配置异步仓储（单例表）。每个方法接收一个 AsyncSession，不在内部管理事务。"""

    async def get_singleton(self, session: AsyncSession) -> VoiceConfig | None:
        result = await session.execute(select(VoiceConfig).where(VoiceConfig.id == VoiceConfig.SINGLETON_ID))
        return result.scalar_one_or_none()

    async def save(self, session: AsyncSession, config: VoiceConfig) -> VoiceConfig:
        session.add(config)
        await session.flush()
        return config
