from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.base_consumer import BaseStreamConsumer
from app.infrastructure.tasks.constants import (
    FIELD_RETRY_COUNT,
    MAX_RETRY_COUNT,
    StreamConfig,
)

_CONFIG = StreamConfig(
    stream_key="test:stream",
    group_name="test-group",
    consumer_prefix="test-consumer-",
    id_field="testId",
)


class FakeConsumer(BaseStreamConsumer[dict[str, Any]]):
    def __init__(self, redis_client: RedisClient) -> None:
        super().__init__(redis_client, _CONFIG)
        self.calls: list[str] = []
        self._skip_ids: set[int] = set()
        self._fail_ids: set[int] = set()

    def task_display_name(self) -> str:
        return "test-task"

    def parse_payload(self, msg_id: str, data: dict[bytes, bytes]) -> dict[str, Any] | None:
        id_val = data.get(b"testId", b"0")
        retry_val = data.get(FIELD_RETRY_COUNT.encode(), b"0")
        return {"id": int(id_val), "retryCount": int(retry_val)}

    def payload_identifier(self, payload: dict[str, Any]) -> str:
        return str(payload["id"])

    def should_skip(self, payload: dict[str, Any]) -> bool:
        return payload["id"] in self._skip_ids

    async def mark_processing(self, payload: dict[str, Any]) -> None:
        self.calls.append(f"mark_processing:{payload['id']}")

    async def process_business(self, payload: dict[str, Any]) -> None:
        self.calls.append(f"process_business:{payload['id']}")
        if payload["id"] in self._fail_ids:
            raise RuntimeError("business failure")

    async def mark_completed(self, payload: dict[str, Any]) -> None:
        self.calls.append(f"mark_completed:{payload['id']}")

    async def mark_failed(self, payload: dict[str, Any], error: str) -> None:
        self.calls.append(f"mark_failed:{payload['id']}:{error}")

    async def retry_message(self, payload: dict[str, Any], retry_count: int) -> None:
        self.calls.append(f"retry_message:{payload['id']}:{retry_count}")


@pytest.fixture()
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def consumer(mock_redis: AsyncMock) -> FakeConsumer:
    return FakeConsumer(RedisClient(mock_redis))


def _make_msg(msg_id: str, payload_id: int, retry_count: int = 0) -> tuple[str, dict[bytes, bytes]]:
    data = {
        b"testId": str(payload_id).encode(),
        FIELD_RETRY_COUNT.encode(): str(retry_count).encode(),
    }
    return (msg_id, data)


class TestProcessMessageStateMachine:
    async def test_success_path_mark_processing_business_completed_ack(
        self, consumer: FakeConsumer, mock_redis: AsyncMock
    ) -> None:
        msg = _make_msg("100-0", 1)
        await consumer._process_message(msg[0], msg[1])

        assert consumer.calls == [
            "mark_processing:1",
            "process_business:1",
            "mark_completed:1",
        ]
        mock_redis.xack.assert_called_once()

    async def test_ack_called_after_success(self, consumer: FakeConsumer, mock_redis: AsyncMock) -> None:
        msg = _make_msg("100-0", 1)
        await consumer._process_message(msg[0], msg[1])
        mock_redis.xack.assert_called_once_with("test:stream", "test-group", "100-0")


class TestShouldSkipIdempotency:
    async def test_skip_ack_without_processing(self, consumer: FakeConsumer, mock_redis: AsyncMock) -> None:
        consumer._skip_ids = {42}
        msg = _make_msg("100-0", 42)
        await consumer._process_message(msg[0], msg[1])

        assert consumer.calls == []
        mock_redis.xack.assert_called_once()

    async def test_non_skipped_processes_normally(self, consumer: FakeConsumer, mock_redis: AsyncMock) -> None:
        consumer._skip_ids = {42}
        msg = _make_msg("100-0", 99)
        await consumer._process_message(msg[0], msg[1])
        assert "mark_processing:99" in consumer.calls
        assert "mark_completed:99" in consumer.calls


class TestParseFailure:
    async def test_none_payload_acks_without_processing(
        self, consumer: FakeConsumer, mock_redis: AsyncMock
    ) -> None:
        consumer.parse_payload = lambda msg_id, data: None  # type: ignore[method-assign]
        msg = _make_msg("100-0", 1)
        await consumer._process_message(msg[0], msg[1])

        assert consumer.calls == []
        mock_redis.xack.assert_called_once()


class TestRetryBoundary:
    async def test_first_failure_retries_with_count_1(
        self, consumer: FakeConsumer, mock_redis: AsyncMock
    ) -> None:
        consumer._fail_ids = {1}
        msg = _make_msg("100-0", 1, retry_count=0)
        await consumer._process_message(msg[0], msg[1])

        assert "mark_processing:1" in consumer.calls
        assert "process_business:1" in consumer.calls
        assert "retry_message:1:1" in consumer.calls
        assert "mark_failed" not in " ".join(consumer.calls)
        mock_redis.xack.assert_called_once()

    async def test_second_failure_retries_with_count_2(
        self, consumer: FakeConsumer, mock_redis: AsyncMock
    ) -> None:
        consumer._fail_ids = {1}
        msg = _make_msg("100-0", 1, retry_count=1)
        await consumer._process_message(msg[0], msg[1])

        assert "retry_message:1:2" in consumer.calls
        assert "mark_failed" not in " ".join(consumer.calls)

    async def test_third_failure_retries_with_count_3(
        self, consumer: FakeConsumer, mock_redis: AsyncMock
    ) -> None:
        consumer._fail_ids = {1}
        msg = _make_msg("100-0", 1, retry_count=2)
        await consumer._process_message(msg[0], msg[1])

        assert "retry_message:1:3" in consumer.calls
        assert "mark_failed" not in " ".join(consumer.calls)

    async def test_fourth_attempt_marks_failed(
        self, consumer: FakeConsumer, mock_redis: AsyncMock
    ) -> None:
        consumer._fail_ids = {1}
        msg = _make_msg("100-0", 1, retry_count=MAX_RETRY_COUNT)
        await consumer._process_message(msg[0], msg[1])

        assert any(c.startswith("mark_failed:1:") for c in consumer.calls)
        assert "retry_message" not in " ".join(consumer.calls)
        mock_redis.xack.assert_called_once()

    async def test_failed_error_message_truncated(self, consumer: FakeConsumer) -> None:
        consumer._fail_ids = {1}
        msg = _make_msg("100-0", 1, retry_count=MAX_RETRY_COUNT)
        await consumer._process_message(msg[0], msg[1])

        failed_call = [c for c in consumer.calls if c.startswith("mark_failed:1:")][0]
        error_msg = failed_call.split("mark_failed:1:")[1]
        assert len(error_msg) <= 500
        assert "business failure" in error_msg


class TestConsumeLoop:
    async def test_processes_messages_from_xreadgroup(
        self, consumer: FakeConsumer, mock_redis: AsyncMock
    ) -> None:
        call_count = 0

        async def fake_xreadgroup(*args: Any, **kwargs: Any) -> list[Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    ("test:stream", [_make_msg("100-0", 1), _make_msg("100-1", 2)])
                ]
            consumer._running = False
            return []

        mock_redis.xautoclaim.return_value = ("0-0", [])
        mock_redis.xreadgroup.side_effect = fake_xreadgroup

        consumer._running = True
        await consumer._consume_loop()

        assert "mark_processing:1" in consumer.calls
        assert "mark_processing:2" in consumer.calls

    async def test_processes_pending_from_xautoclaim(
        self, consumer: FakeConsumer, mock_redis: AsyncMock
    ) -> None:
        call_count = 0

        async def fake_xautoclaim(*args: Any, **kwargs: Any) -> tuple[Any, list[Any]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ("0-0", [_make_msg("200-0", 3)])
            consumer._running = False
            return ("0-0", [])

        mock_redis.xautoclaim.side_effect = fake_xautoclaim
        mock_redis.xreadgroup.return_value = []

        consumer._running = True
        await consumer._consume_loop()

        assert "mark_processing:3" in consumer.calls
