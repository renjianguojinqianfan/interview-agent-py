import logging
from abc import ABC, abstractmethod

from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.constants import STREAM_MAX_LEN, StreamConfig
from app.infrastructure.tasks.utils import truncate_error

logger = logging.getLogger(__name__)


class BaseStreamProducer[T](ABC):
    def __init__(self, redis_client: RedisClient, config: StreamConfig) -> None:
        self._redis = redis_client
        self._config = config

    async def send_task(self, payload: T) -> str:
        try:
            message_id = await self._redis.xadd(
                self._config.stream_key,
                self.build_message(payload),
                max_len=STREAM_MAX_LEN,
            )
            logger.info(
                "%s任务已发送: %s, messageId=%s",
                self.task_display_name(),
                self.payload_identifier(payload),
                message_id,
            )
            return message_id
        except Exception as e:
            error = truncate_error(str(e))
            logger.error(
                "%s任务发送失败: %s, error=%s",
                self.task_display_name(),
                self.payload_identifier(payload),
                error,
            )
            await self.on_send_failed(payload, f"任务入队失败: {error}")
            return ""

    @abstractmethod
    def task_display_name(self) -> str:
        ...

    @abstractmethod
    def build_message(self, payload: T) -> dict[str, str]:
        ...

    @abstractmethod
    def payload_identifier(self, payload: T) -> str:
        ...

    @abstractmethod
    async def on_send_failed(self, payload: T, error: str) -> None:
        ...
