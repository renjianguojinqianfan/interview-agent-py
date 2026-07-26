import logging

from app.application.knowledgebase.generation_service import QuestionGenerationService
from app.application.knowledgebase.generation_state_service import QuestionGenerationStateService
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.base_consumer import BaseStreamConsumer
from app.infrastructure.tasks.constants import FIELD_TASK_ID, StreamConfig
from app.infrastructure.tasks.question_gen_producer import QuestionGenPayload, QuestionGenProducer

logger = logging.getLogger(__name__)


class QuestionGenConsumer(BaseStreamConsumer[QuestionGenPayload]):
    """题目生成消费者：try_mark_processing 原子领取（行锁 + taskId 匹配），领取失败静默 ACK 丢弃。

    题目替换与 COMPLETED 在 state_service 同一事务内提交，故 mark_completed 为 no-op；
    重试前先 reset_for_retry（PROCESSING -> QUEUED），任务已失效则不再重投。
    """

    def __init__(
        self,
        redis_client: RedisClient,
        config: StreamConfig,
        state_service: QuestionGenerationStateService,
        generation_service: QuestionGenerationService,
        producer: QuestionGenProducer,
    ) -> None:
        super().__init__(redis_client, config)
        self._state_service = state_service
        self._generation_service = generation_service
        self._producer = producer

    def task_display_name(self) -> str:
        return "题目生成"

    def parse_payload(self, msg_id: str, data: dict[bytes, bytes]) -> QuestionGenPayload | None:
        kb_id_raw = data.get(self._config.id_field.encode())
        task_id_raw = data.get(FIELD_TASK_ID.encode())
        if kb_id_raw is None or task_id_raw is None:
            logger.warning("题目生成消息格式错误，丢弃: msgId=%s", msg_id)
            return None
        try:
            return QuestionGenPayload(kb_id=int(kb_id_raw), task_id=task_id_raw.decode())
        except (ValueError, TypeError):
            logger.warning("题目生成消息解析失败，丢弃: msgId=%s", msg_id)
            return None

    def payload_identifier(self, payload: QuestionGenPayload) -> str:
        return f"kbId={payload.kb_id}, taskId={payload.task_id}"

    async def mark_processing(self, payload: QuestionGenPayload) -> None:
        """无操作：领取语义由 try_mark_processing 承担。"""

    async def try_mark_processing(self, payload: QuestionGenPayload) -> bool:
        return await self._state_service.try_mark_processing(payload.kb_id, payload.task_id)

    async def process_business(self, payload: QuestionGenPayload) -> None:
        config = await self._state_service.get_config(payload.kb_id, payload.task_id)
        await self._generation_service.execute_generation(payload.kb_id, payload.task_id, config)

    async def mark_completed(self, payload: QuestionGenPayload) -> None:
        """无操作：题目替换与 COMPLETED 已在同一事务中提交。"""

    async def mark_failed(self, payload: QuestionGenPayload, error: str) -> None:
        await self._state_service.mark_failed(payload.kb_id, payload.task_id)

    async def retry_message(self, payload: QuestionGenPayload, retry_count: int) -> None:
        if not await self._state_service.reset_for_retry(payload.kb_id, payload.task_id):
            logger.info("题目生成任务已失效，不再重试: kbId=%s, taskId=%s", payload.kb_id, payload.task_id)
            return
        await self._producer.send_task(
            QuestionGenPayload(kb_id=payload.kb_id, task_id=payload.task_id, retry_count=retry_count)
        )
