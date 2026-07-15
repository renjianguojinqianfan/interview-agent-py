import asyncio
import logging
import uuid
from abc import ABC, abstractmethod

from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.constants import (
    BATCH_SIZE,
    FIELD_RETRY_COUNT,
    MAX_RETRY_COUNT,
    PENDING_CLAIM_BATCH_SIZE,
    PENDING_IDLE_TIMEOUT_MS,
    POLL_INTERVAL_MS,
    StreamConfig,
)
from app.infrastructure.tasks.utils import truncate_error

logger = logging.getLogger(__name__)


class BaseStreamConsumer[T](ABC):
    def __init__(self, redis_client: RedisClient, config: StreamConfig) -> None:
        self._redis = redis_client
        self._config = config
        self._consumer_name = f"{config.consumer_prefix}{uuid.uuid4().hex[:8]}"
        self._running = False

    async def start(self) -> None:
        self._running = True
        await self._redis.create_stream_group(self._config.stream_key, self._config.group_name)
        asyncio.create_task(self._consume_loop())
        logger.info("%s consumer started: %s", self.task_display_name(), self._consumer_name)

    async def stop(self) -> None:
        self._running = False
        logger.info("%s consumer stopped: %s", self.task_display_name(), self._consumer_name)

    async def _consume_loop(self) -> None:
        while self._running:
            try:
                next_id, claimed = await self._redis.xautoclaim(
                    self._config.stream_key,
                    self._config.group_name,
                    self._consumer_name,
                    min_idle_ms=PENDING_IDLE_TIMEOUT_MS,
                    count=PENDING_CLAIM_BATCH_SIZE,
                )
                for msg_id, data in claimed:
                    await self._process_message(msg_id, data)

                results = await self._redis.xreadgroup(
                    self._config.stream_key,
                    self._config.group_name,
                    self._consumer_name,
                    count=BATCH_SIZE,
                    block_ms=POLL_INTERVAL_MS,
                )
                for _stream, messages in results:
                    for msg_id, data in messages:
                        await self._process_message(msg_id, data)
            except Exception as e:
                if not self._running:
                    break
                logger.error("%s consume loop error: %s", self.task_display_name(), e)

            await asyncio.sleep(0)

    async def _process_message(self, msg_id: str, data: dict[bytes, bytes]) -> None:
        try:
            payload = self.parse_payload(msg_id, data)
        except Exception as e:
            logger.warning(
                "%s parse failed, ack and discard: msgId=%s, error=%s",
                self.task_display_name(),
                msg_id,
                e,
            )
            await self._ack(msg_id)
            return

        if payload is None:
            await self._ack(msg_id)
            return

        retry_count = self._parse_retry_count(data)
        logger.info(
            "%s processing: payload=%s, msgId=%s, retryCount=%d",
            self.task_display_name(),
            self.payload_identifier(payload),
            msg_id,
            retry_count,
        )

        try:
            if self.should_skip(payload):
                logger.info("%s skipped: %s", self.task_display_name(), self.payload_identifier(payload))
                await self._ack(msg_id)
                return

            await self.mark_processing(payload)
            await self.process_business(payload)
            await self.mark_completed(payload)
            await self._ack(msg_id)
            logger.info("%s completed: %s", self.task_display_name(), self.payload_identifier(payload))
        except Exception as e:
            logger.error("%s failed: %s, error=%s", self.task_display_name(), self.payload_identifier(payload), e)
            if retry_count < MAX_RETRY_COUNT:
                await self.retry_message(payload, retry_count + 1)
            else:
                await self.mark_failed(payload, truncate_error(str(e)))
            await self._ack(msg_id)

    def _parse_retry_count(self, data: dict[bytes, bytes]) -> int:
        try:
            return int(data.get(FIELD_RETRY_COUNT.encode(), b"0"))
        except (ValueError, TypeError):
            return 0

    async def _ack(self, msg_id: str) -> None:
        try:
            await self._redis.xack(self._config.stream_key, self._config.group_name, msg_id)
        except Exception as e:
            logger.error("%s ack failed: msgId=%s, error=%s", self.task_display_name(), msg_id, e)

    @abstractmethod
    def task_display_name(self) -> str: ...

    @abstractmethod
    def parse_payload(self, msg_id: str, data: dict[bytes, bytes]) -> T | None: ...

    @abstractmethod
    def payload_identifier(self, payload: T) -> str: ...

    def should_skip(self, payload: T) -> bool:
        return False

    @abstractmethod
    async def mark_processing(self, payload: T) -> None: ...

    @abstractmethod
    async def process_business(self, payload: T) -> None: ...

    @abstractmethod
    async def mark_completed(self, payload: T) -> None: ...

    @abstractmethod
    async def mark_failed(self, payload: T, error: str) -> None: ...

    @abstractmethod
    async def retry_message(self, payload: T, retry_count: int) -> None: ...
