from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ResponseError

from app.infrastructure.redis.client import RedisClient


@pytest.fixture()
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def client(mock_redis: AsyncMock) -> RedisClient:
    return RedisClient(mock_redis)


class TestCreateStreamGroup:
    async def test_creates_group_with_mkstream(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        await client.create_stream_group("test:stream", "test-group")
        mock_redis.xgroup_create.assert_called_once_with(
            "test:stream", "test-group", id="0", mkstream=True
        )

    async def test_ignores_busygroup_error(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.xgroup_create.side_effect = ResponseError("BUSYGROUP Consumer Group name already exists")
        await client.create_stream_group("test:stream", "test-group")

    async def test_reraises_non_busygroup_error(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.xgroup_create.side_effect = ResponseError("OTHER ERROR")
        with pytest.raises(ResponseError):
            await client.create_stream_group("test:stream", "test-group")


class TestXAdd:
    async def test_adds_message_with_maxlen(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.xadd.return_value = "1234567890-0"
        result = await client.xadd("test:stream", {"field": "value"}, max_len=1000)
        assert result == "1234567890-0"
        mock_redis.xadd.assert_called_once_with(
            "test:stream", {"field": "value"}, maxlen=1000, approximate=True
        )


class TestXReadGroup:
    async def test_reads_new_messages(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.xreadgroup.return_value = [
            ("test:stream", [(b"123-0", {b"field": b"value"})])
        ]
        result = await client.xreadgroup("test:stream", "group", "consumer", count=10, block_ms=1000)
        assert len(result) == 1
        mock_redis.xreadgroup.assert_called_once_with(
            "group", "consumer", {"test:stream": ">"}, count=10, block=1000
        )


class TestXAutoClaim:
    async def test_claims_pending_messages(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.xautoclaim.return_value = (b"0-0", [(b"123-0", {b"field": b"value"})])
        next_id, messages = await client.xautoclaim("test:stream", "group", "consumer", min_idle_ms=300000, count=10)
        assert next_id == b"0-0"
        assert len(messages) == 1
        mock_redis.xautoclaim.assert_called_once_with(
            "test:stream", "group", "consumer", min_idle_time=300000, count=10
        )


class TestXAck:
    async def test_acks_message(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.xack.return_value = 1
        result = await client.xack("test:stream", "group", "123-0")
        assert result == 1
        mock_redis.xack.assert_called_once_with("test:stream", "group", "123-0")
