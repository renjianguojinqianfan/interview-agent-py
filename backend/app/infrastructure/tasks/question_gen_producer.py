import logging
from dataclasses import dataclass

from app.application.knowledgebase.generation_state_service import QuestionGenerationStateService
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.base_producer import BaseStreamProducer
from app.infrastructure.tasks.constants import FIELD_RETRY_COUNT, FIELD_TASK_ID, StreamConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuestionGenPayload:
    kb_id: int
    task_id: str
    retry_count: int = 0


class QuestionGenProducer(BaseStreamProducer[QuestionGenPayload]):
    """题目生成任务生产者：kbId + taskId 投递到 knowledgebase:question-gen:stream。

    入队失败即标记任务 FAILED（安全文案），避免 QUEUED 卡死等恢复 job 兜底。
    """

    def __init__(
        self,
        redis_client: RedisClient,
        config: StreamConfig,
        state_service: QuestionGenerationStateService,
    ) -> None:
        super().__init__(redis_client, config)
        self._state_service = state_service

    def task_display_name(self) -> str:
        return "题目生成"

    def build_message(self, payload: QuestionGenPayload) -> dict[str, str]:
        return {
            self._config.id_field: str(payload.kb_id),
            FIELD_TASK_ID: payload.task_id,
            FIELD_RETRY_COUNT: str(payload.retry_count),
        }

    def payload_identifier(self, payload: QuestionGenPayload) -> str:
        return f"kbId={payload.kb_id}, taskId={payload.task_id}"

    async def on_send_failed(self, payload: QuestionGenPayload, error: str) -> None:
        try:
            await self._state_service.mark_failed(payload.kb_id, payload.task_id)
            logger.warning("题目生成入队失败，已标记 FAILED: kbId=%s, taskId=%s", payload.kb_id, payload.task_id)
        except Exception as e:
            logger.error("标记题目生成入队失败状态时出错: kbId=%s, error=%s", payload.kb_id, e)
