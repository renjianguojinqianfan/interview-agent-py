from unittest.mock import AsyncMock

import pytest

from app.infrastructure.redis.client import RedisClient


@pytest.fixture()
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def client(mock_redis: AsyncMock) -> RedisClient:
    return RedisClient(mock_redis)


class TestHSet:
    async def test_encodes_key_and_fields(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        await client.hset("session:123", {"status": "CREATED", "index": "0"})
        mock_redis.hset.assert_called_once_with(
            b"session:123",
            mapping={b"status": b"CREATED", b"index": b"0"},
        )


class TestHGetAll:
    async def test_decodes_all_fields(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.hgetall.return_value = {b"status": b"CREATED", b"index": b"0"}
        result = await client.hgetall("session:123")
        assert result == {"status": "CREATED", "index": "0"}
        mock_redis.hgetall.assert_called_once_with(b"session:123")

    async def test_returns_empty_when_key_missing(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.hgetall.return_value = {}
        assert await client.hgetall("missing") == {}


class TestGet:
    async def test_returns_decoded_value(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.get.return_value = b"abc123"
        assert await client.get("resume:1:unfinished") == "abc123"
        mock_redis.get.assert_called_once_with(b"resume:1:unfinished")

    async def test_returns_none_when_missing(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.get.return_value = None
        assert await client.get("missing") is None


class TestSet:
    async def test_sets_value_without_ttl(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        await client.set("key", "value")
        mock_redis.set.assert_called_once_with(b"key", b"value", ex=None)

    async def test_sets_value_with_ttl(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        await client.set("key", "value", ex=3600)
        mock_redis.set.assert_called_once_with(b"key", b"value", ex=3600)


class TestDelete:
    async def test_deletes_key(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.delete.return_value = 1
        result = await client.delete("key")
        assert result == 1
        mock_redis.delete.assert_called_once_with(b"key")


class TestExpire:
    async def test_sets_expiry(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        await client.expire("key", 3600)
        mock_redis.expire.assert_called_once_with(b"key", 3600)


class TestTtl:
    async def test_returns_ttl(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.ttl.return_value = 3600
        assert await client.ttl("key") == 3600
        mock_redis.ttl.assert_called_once_with(b"key")
