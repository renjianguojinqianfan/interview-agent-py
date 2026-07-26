"""题目生成任务对单元测试（producer 入队失败标失败 + consumer 原子领取/重试语义）。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.constants import KB_QUESTION_GEN
from app.infrastructure.tasks.question_gen_consumer import QuestionGenConsumer
from app.infrastructure.tasks.question_gen_producer import QuestionGenPayload, QuestionGenProducer


@pytest.fixture()
def mock_redis() -> AsyncMock:
    return AsyncMock()


def _mock_state_service() -> MagicMock:
    state = MagicMock()
    state.try_mark_processing = AsyncMock(return_value=True)
    state.reset_for_retry = AsyncMock(return_value=True)
    state.mark_failed = AsyncMock(return_value=True)
    state.get_config = AsyncMock()
    return state


class TestProducer:
    def _producer(self, mock_redis: AsyncMock, state: MagicMock) -> QuestionGenProducer:
        return QuestionGenProducer(RedisClient(mock_redis), KB_QUESTION_GEN, state)

    async def test_message_carries_kb_id_task_id_retry_count(self, mock_redis: AsyncMock) -> None:
        producer = self._producer(mock_redis, _mock_state_service())

        await producer.send_task(QuestionGenPayload(kb_id=1, task_id="task-1"))

        message = mock_redis.xadd.call_args.args[1]
        assert message == {"knowledgeBaseId": "1", "taskId": "task-1", "retryCount": "0"}

    async def test_send_failure_marks_task_failed(self, mock_redis: AsyncMock) -> None:
        state = _mock_state_service()
        producer = self._producer(mock_redis, state)
        mock_redis.xadd.side_effect = RuntimeError("redis down")

        await producer.send_task(QuestionGenPayload(kb_id=1, task_id="task-1"))

        state.mark_failed.assert_awaited_once_with(1, "task-1")


class TestConsumer:
    def _consumer(
        self,
        mock_redis: AsyncMock,
        state: MagicMock,
        generation_service: MagicMock | None = None,
        producer: MagicMock | None = None,
    ) -> QuestionGenConsumer:
        if generation_service is None:
            generation_service = MagicMock()
            generation_service.execute_generation = AsyncMock()
        if producer is None:
            producer = MagicMock()
            producer.send_task = AsyncMock()
        return QuestionGenConsumer(RedisClient(mock_redis), KB_QUESTION_GEN, state, generation_service, producer)

    def _msg(self, kb_id: int = 1, task_id: str = "task-1", retry: int = 0) -> dict[bytes, bytes]:
        return {
            b"knowledgeBaseId": str(kb_id).encode(),
            b"taskId": task_id.encode(),
            b"retryCount": str(retry).encode(),
        }

    def test_parse_payload(self, mock_redis: AsyncMock) -> None:
        consumer = self._consumer(mock_redis, _mock_state_service())

        payload = consumer.parse_payload("100-0", self._msg(kb_id=7, task_id="t-9"))

        assert payload == QuestionGenPayload(kb_id=7, task_id="t-9")

    def test_parse_payload_missing_fields_returns_none(self, mock_redis: AsyncMock) -> None:
        consumer = self._consumer(mock_redis, _mock_state_service())

        assert consumer.parse_payload("100-0", {b"knowledgeBaseId": b"7"}) is None
        assert consumer.parse_payload("100-0", {b"taskId": b"t"}) is None

    async def test_claim_rejected_message_discarded(self, mock_redis: AsyncMock) -> None:
        state = _mock_state_service()
        state.try_mark_processing.return_value = False
        generation = MagicMock()
        generation.execute_generation = AsyncMock()
        consumer = self._consumer(mock_redis, state, generation)

        await consumer._process_message("100-0", self._msg())

        generation.execute_generation.assert_not_awaited()
        mock_redis.xack.assert_called_once()

    async def test_business_fetches_config_and_generates(self, mock_redis: AsyncMock) -> None:
        state = _mock_state_service()
        config = MagicMock()
        state.get_config.return_value = config
        generation = MagicMock()
        generation.execute_generation = AsyncMock()
        consumer = self._consumer(mock_redis, state, generation)

        await consumer._process_message("100-0", self._msg())

        state.get_config.assert_awaited_once_with(1, "task-1")
        generation.execute_generation.assert_awaited_once_with(1, "task-1", config)

    async def test_retry_requeues_only_after_reset(self, mock_redis: AsyncMock) -> None:
        state = _mock_state_service()
        generation = MagicMock()
        generation.execute_generation = AsyncMock(side_effect=RuntimeError("llm down"))
        producer = MagicMock()
        producer.send_task = AsyncMock()
        consumer = self._consumer(mock_redis, state, generation, producer)

        await consumer._process_message("100-0", self._msg(retry=0))

        state.reset_for_retry.assert_awaited_once_with(1, "task-1")
        sent: QuestionGenPayload = producer.send_task.await_args.args[0]
        assert sent.retry_count == 1

    async def test_retry_skipped_when_task_stale(self, mock_redis: AsyncMock) -> None:
        state = _mock_state_service()
        state.reset_for_retry.return_value = False
        generation = MagicMock()
        generation.execute_generation = AsyncMock(side_effect=RuntimeError("llm down"))
        producer = MagicMock()
        producer.send_task = AsyncMock()
        consumer = self._consumer(mock_redis, state, generation, producer)

        await consumer._process_message("100-0", self._msg(retry=0))

        producer.send_task.assert_not_awaited()

    async def test_final_failure_marks_failed(self, mock_redis: AsyncMock) -> None:
        state = _mock_state_service()
        generation = MagicMock()
        generation.execute_generation = AsyncMock(side_effect=RuntimeError("llm down"))
        consumer = self._consumer(mock_redis, state, generation)

        await consumer._process_message("100-0", self._msg(retry=3))

        state.mark_failed.assert_awaited_once_with(1, "task-1")
