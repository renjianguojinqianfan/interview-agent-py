import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities.task_status import AsyncTaskStatus
from app.infrastructure.db.repositories.interview_repository import InterviewRepository
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.base_producer import BaseStreamProducer
from app.infrastructure.tasks.constants import FIELD_RETRY_COUNT, StreamConfig
from app.infrastructure.tasks.utils import truncate_error

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvaluatePayload:
    session_id: str


class EvaluateStreamProducer(BaseStreamProducer[EvaluatePayload]):
    """面试评估任务生产者：将 sessionId 投递到 interview:evaluate:stream。

    消费者在 #9 实现（EvaluateStreamConsumer）。
    """

    def __init__(
        self,
        redis_client: RedisClient,
        config: StreamConfig,
        session_factory: async_sessionmaker[AsyncSession],
        repository: InterviewRepository,
    ) -> None:
        super().__init__(redis_client, config)
        self._session_factory = session_factory
        self._repository = repository

    def task_display_name(self) -> str:
        return "面试评估"

    def build_message(self, payload: EvaluatePayload) -> dict[str, str]:
        return {
            self._config.id_field: payload.session_id,
            FIELD_RETRY_COUNT: "0",
        }

    def payload_identifier(self, payload: EvaluatePayload) -> str:
        return f"sessionId={payload.session_id}"

    async def on_send_failed(self, payload: EvaluatePayload, error: str) -> None:
        try:
            async with self._session_factory() as session:
                interview_session = await self._repository.find_by_session_id(session, payload.session_id)
                if interview_session is not None:
                    await self._repository.update_evaluate_status(
                        session,
                        interview_session,
                        AsyncTaskStatus.FAILED.value,
                        truncate_error(error),
                    )
                    await session.commit()
                    logger.warning(
                        "面试评估入队失败，已标记 FAILED: sessionId=%s",
                        payload.session_id,
                    )
        except Exception as e:
            logger.error(
                "标记评估入队失败状态时出错: sessionId=%s, error=%s",
                payload.session_id,
                e,
            )
