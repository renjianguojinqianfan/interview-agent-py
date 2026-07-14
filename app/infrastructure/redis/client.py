import logging
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

logger = logging.getLogger(__name__)


class RedisClient:
    def __init__(self, redis: Any = None) -> None:
        self._redis = redis

    async def create_stream_group(self, stream_key: str, group_name: str) -> None:
        try:
            await self._redis.xgroup_create(stream_key, group_name, id="0", mkstream=True)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
            logger.debug("Stream group already exists: %s", group_name)

    async def xadd(self, stream_key: str, fields: dict[str, str], max_len: int) -> str:
        result = await self._redis.xadd(stream_key, fields, maxlen=max_len, approximate=True)
        return str(result)

    async def xreadgroup(
        self,
        stream_key: str,
        group_name: str,
        consumer_name: str,
        count: int,
        block_ms: int,
    ) -> list[Any]:
        result: list[Any] = await self._redis.xreadgroup(
            group_name,
            consumer_name,
            {stream_key: ">"},
            count=count,
            block=block_ms,
        )
        return result

    async def xautoclaim(
        self,
        stream_key: str,
        group_name: str,
        consumer_name: str,
        min_idle_ms: int,
        count: int,
    ) -> tuple[Any, list[Any]]:
        result: tuple[Any, list[Any]] = await self._redis.xautoclaim(
            stream_key,
            group_name,
            consumer_name,
            min_idle_time=min_idle_ms,
            count=count,
        )
        return result

    async def xack(self, stream_key: str, group_name: str, message_id: str) -> int:
        result = await self._redis.xack(stream_key, group_name, message_id)
        return int(result)


def create_redis_client() -> RedisClient:
    from app.config.settings import settings

    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    return RedisClient(redis)
