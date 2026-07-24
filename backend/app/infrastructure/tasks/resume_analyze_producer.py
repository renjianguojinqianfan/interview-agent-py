import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities.task_status import AsyncTaskStatus
from app.infrastructure.db.repositories.resume_repository import ResumeRepository
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.base_producer import BaseStreamProducer
from app.infrastructure.tasks.constants import FIELD_RETRY_COUNT, StreamConfig
from app.infrastructure.tasks.utils import truncate_error

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResumeAnalyzePayload:
    resume_id: int


class AnalyzeStreamProducer(BaseStreamProducer[ResumeAnalyzePayload]):
    """简历分析任务生产者：将 resumeId 投递到 resume:analyze:stream。"""

    def __init__(
        self,
        redis_client: RedisClient,
        config: StreamConfig,
        session_factory: async_sessionmaker[AsyncSession],
        repository: ResumeRepository,
    ) -> None:
        super().__init__(redis_client, config)
        self._session_factory = session_factory
        self._repository = repository

    def task_display_name(self) -> str:
        return "简历分析"

    def build_message(self, payload: ResumeAnalyzePayload) -> dict[str, str]:
        return {
            self._config.id_field: str(payload.resume_id),
            FIELD_RETRY_COUNT: "0",
        }

    def payload_identifier(self, payload: ResumeAnalyzePayload) -> str:
        return f"resumeId={payload.resume_id}"

    async def on_send_failed(self, payload: ResumeAnalyzePayload, error: str) -> None:
        try:
            async with self._session_factory() as session:
                resume = await self._repository.get_by_id(session, payload.resume_id)
                if resume is not None:
                    await self._repository.update_analyze_status(
                        session, resume, AsyncTaskStatus.FAILED.value, truncate_error(error)
                    )
                    await session.commit()
                    logger.warning("简历分析入队失败，已标记 FAILED: resumeId=%s", payload.resume_id)
        except Exception as e:
            logger.error("标记分析入队失败状态时出错: resumeId=%s, error=%s", payload.resume_id, e)
