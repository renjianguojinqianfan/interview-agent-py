import logging
from typing import cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError

logger = logging.getLogger(__name__)

type StreamMessage = tuple[str, dict[bytes, bytes]]
type StreamMessages = list[tuple[str, list[StreamMessage]]]


class RedisClient:
    def __init__(self, redis: Redis | None = None) -> None:
        self._redis = redis

    @property
    def _conn(self) -> Redis:
        if self._redis is None:
            raise RuntimeError("Redis client not initialized")
        return self._redis

    async def create_stream_group(self, stream_key: str, group_name: str) -> None:
        try:
            await self._conn.xgroup_create(stream_key, group_name, id="0", mkstream=True)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
            logger.debug("Stream group already exists: %s", group_name)

    async def xadd(self, stream_key: str, fields: dict[str, str], max_len: int) -> str:
        result = await self._conn.xadd(
            stream_key,
            fields,  # type: ignore[arg-type]
            maxlen=max_len,
            approximate=True,
        )
        return str(result)

    async def xreadgroup(
        self,
        stream_key: str,
        group_name: str,
        consumer_name: str,
        count: int,
        block_ms: int,
    ) -> StreamMessages:
        result = await self._conn.xreadgroup(
            group_name,
            consumer_name,
            {stream_key: ">"},
            count=count,
            block=block_ms,
        )
        return cast(StreamMessages, result)

    async def xautoclaim(
        self,
        stream_key: str,
        group_name: str,
        consumer_name: str,
        min_idle_ms: int,
        count: int,
    ) -> tuple[str, list[StreamMessage]]:
        result = await self._conn.xautoclaim(
            stream_key,
            group_name,
            consumer_name,
            min_idle_time=min_idle_ms,
            count=count,
        )
        return result[0], cast(list[StreamMessage], result[1])

    async def xack(self, stream_key: str, group_name: str, message_id: str) -> int:
        result = await self._conn.xack(stream_key, group_name, message_id)
        return int(result)


def create_redis_client() -> RedisClient:
    from app.config.settings import settings

    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    return RedisClient(redis)
