from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.base_producer import BaseStreamProducer
from app.infrastructure.tasks.constants import STREAM_MAX_LEN, StreamConfig

_CONFIG = StreamConfig(
    stream_key="test:stream",
    group_name="test-group",
    consumer_prefix="test-consumer-",
    id_field="testId",
)


class FakeProducer(BaseStreamProducer[dict[str, Any]]):
    def __init__(self, redis_client: RedisClient) -> None:
        super().__init__(redis_client, _CONFIG)
        self.send_failed_calls: list[tuple[dict[str, Any], str]] = []

    def task_display_name(self) -> str:
        return "test-producer"

    def build_message(self, payload: dict[str, Any]) -> dict[str, str]:
        return {"testId": str(payload["id"]), "data": payload["data"]}

    def payload_identifier(self, payload: dict[str, Any]) -> str:
        return str(payload["id"])

    async def on_send_failed(self, payload: dict[str, Any], error: str) -> None:
        self.send_failed_calls.append((payload, error))


@pytest.fixture()
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def producer(mock_redis: AsyncMock) -> FakeProducer:
    return FakeProducer(RedisClient(mock_redis))


class TestSendTask:
    async def test_calls_xadd_with_message(self, producer: FakeProducer, mock_redis: AsyncMock) -> None:
        mock_redis.xadd.return_value = "100-0"
        await producer.send_task({"id": 1, "data": "hello"})

        mock_redis.xadd.assert_called_once_with(
            "test:stream",
            {"testId": "1", "data": "hello"},
            maxlen=STREAM_MAX_LEN,
            approximate=True,
        )

    async def test_returns_message_id(self, producer: FakeProducer, mock_redis: AsyncMock) -> None:
        mock_redis.xadd.return_value = "100-0"
        result = await producer.send_task({"id": 1, "data": "hello"})
        assert result == "100-0"

    async def test_send_failure_calls_on_send_failed(
        self, producer: FakeProducer, mock_redis: AsyncMock
    ) -> None:
        mock_redis.xadd.side_effect = RuntimeError("Redis error")
        await producer.send_task({"id": 42, "data": "fail"})

        assert len(producer.send_failed_calls) == 1
        payload, error = producer.send_failed_calls[0]
        assert payload["id"] == 42
        assert "Redis error" in error

    async def test_send_failure_does_not_raise(self, producer: FakeProducer, mock_redis: AsyncMock) -> None:
        mock_redis.xadd.side_effect = RuntimeError("Redis error")
        result = await producer.send_task({"id": 1, "data": "fail"})
        assert result == ""
