import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities.task_status import AsyncTaskStatus
from app.infrastructure.db.repositories.voice_interview_repository import VoiceInterviewRepository
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.base_producer import BaseStreamProducer
from app.infrastructure.tasks.constants import FIELD_RETRY_COUNT, StreamConfig
from app.infrastructure.tasks.utils import truncate_error

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VoiceEvaluatePayload:
    """语音评估任务载荷：sessionId 为 VoiceInterviewSession 主键（数字）。"""

    session_id: int


class VoiceEvaluateStreamProducer(BaseStreamProducer[VoiceEvaluatePayload]):
    """语音面试评估任务生产者：将 sessionId 投递到 voice:evaluate:stream。

    消费者在 VoiceEvaluateStreamConsumer（#14）。事务后发送遵循 ADR-0008 显式顺序。
    """

    def __init__(
        self,
        redis_client: RedisClient,
        config: StreamConfig,
        session_factory: async_sessionmaker[AsyncSession],
        repository: VoiceInterviewRepository,
    ) -> None:
        super().__init__(redis_client, config)
        self._session_factory = session_factory
        self._repository = repository

    def task_display_name(self) -> str:
        return "语音面试评估"

    def build_message(self, payload: VoiceEvaluatePayload) -> dict[str, str]:
        return {
            self._config.id_field: str(payload.session_id),
            FIELD_RETRY_COUNT: "0",
        }

    def payload_identifier(self, payload: VoiceEvaluatePayload) -> str:
        return f"sessionId={payload.session_id}"

    async def on_send_failed(self, payload: VoiceEvaluatePayload, error: str) -> None:
        try:
            async with self._session_factory() as session:
                voice_session = await self._repository.get_by_id(session, payload.session_id)
                if voice_session is not None:
                    await self._repository.update_evaluate_status(
                        session,
                        voice_session,
                        AsyncTaskStatus.FAILED.value,
                        truncate_error(error),
                    )
                    await session.commit()
                    logger.warning(
                        "语音面试评估入队失败，已标记 FAILED: sessionId=%s",
                        payload.session_id,
                    )
        except Exception as e:
            logger.error(
                "标记语音评估入队失败状态时出错: sessionId=%s, error=%s",
                payload.session_id,
                e,
            )
