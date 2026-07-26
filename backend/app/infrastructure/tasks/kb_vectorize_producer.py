import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.entities.task_status import AsyncTaskStatus
from app.infrastructure.db.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.base_producer import BaseStreamProducer
from app.infrastructure.tasks.constants import FIELD_RETRY_COUNT, StreamConfig
from app.infrastructure.tasks.utils import truncate_error

logger = logging.getLogger(__name__)

# ADR-0018：文档粒度向量化消息的可选字段
FIELD_DOCUMENT_ID = "documentId"


@dataclass(frozen=True)
class KbVectorizePayload:
    knowledge_base_id: int
    # ADR-0018：文档粒度向量化； None 表示整库粒度（兼容存量队列消息）
    document_id: int | None = None


class VectorizeStreamProducer(BaseStreamProducer[KbVectorizePayload]):
    """知识库向量化任务生产者：将 knowledgeBaseId 投递到 knowledgebase:vectorize:stream。"""

    def __init__(
        self,
        redis_client: RedisClient,
        config: StreamConfig,
        session_factory: async_sessionmaker[AsyncSession],
        repository: KnowledgeBaseRepository,
    ) -> None:
        super().__init__(redis_client, config)
        self._session_factory = session_factory
        self._repository = repository

    def task_display_name(self) -> str:
        return "知识库向量化"

    def build_message(self, payload: KbVectorizePayload) -> dict[str, str]:
        message = {
            self._config.id_field: str(payload.knowledge_base_id),
            FIELD_RETRY_COUNT: "0",
        }
        if payload.document_id is not None:
            message[FIELD_DOCUMENT_ID] = str(payload.document_id)
        return message

    def payload_identifier(self, payload: KbVectorizePayload) -> str:
        if payload.document_id is not None:
            return f"knowledgeBaseId={payload.knowledge_base_id}, documentId={payload.document_id}"
        return f"knowledgeBaseId={payload.knowledge_base_id}"

    async def on_send_failed(self, payload: KbVectorizePayload, error: str) -> None:
        try:
            async with self._session_factory() as session:
                kb = await self._repository.get_by_id(session, payload.knowledge_base_id)
                if kb is not None:
                    await self._repository.update_vector_status(
                        session, kb, AsyncTaskStatus.FAILED.value, truncate_error(error)
                    )
                    await session.commit()
                    logger.warning("向量化入队失败，已标记 FAILED: knowledgeBaseId=%s", payload.knowledge_base_id)
        except Exception as e:
            logger.error("标记向量化入队失败状态时出错: knowledgeBaseId=%s, error=%s", payload.knowledge_base_id, e)
