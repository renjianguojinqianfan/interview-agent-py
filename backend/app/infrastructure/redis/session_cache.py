"""面试会话 Redis 缓存：双写策略（先 DB 后 Redis）、resume->session 映射、TTL 24h。

Redis 连接 decode_responses=False，所有 key/value 在 RedisClient 层做 bytes<->str 转换。
JSON 序列化/反序列化在本层处理。
"""

from dataclasses import dataclass

from app.domain.entities.interview import SESSION_TTL_SECONDS, SessionStatus
from app.infrastructure.redis.client import RedisClient

_SESSION_KEY = "interview:session:{session_id}"
_UNFINISHED_KEY = "interview:resume:{resume_id}:unfinished"

_FIELD_RESUME_TEXT = "resumeText"
_FIELD_RESUME_ID = "resumeId"
_FIELD_QUESTIONS_JSON = "questionsJson"
_FIELD_CURRENT_INDEX = "currentIndex"
_FIELD_STATUS = "status"

_UNFINISHED_STATUSES = (SessionStatus.CREATED.value, SessionStatus.IN_PROGRESS.value)


@dataclass(frozen=True)
class CachedSession:
    """Redis 缓存的会话快照。"""

    session_id: str
    resume_text: str
    resume_id: int | None
    questions_json: str
    current_index: int
    status: str


class InterviewSessionCache:
    """面试会话缓存。Redis 失败仅 warn，由调用方决定是否从 DB 恢复。"""

    def __init__(
        self,
        redis_client: RedisClient,
        ttl: int = SESSION_TTL_SECONDS,
    ) -> None:
        self._redis = redis_client
        self._ttl = ttl

    async def save_session(
        self,
        session_id: str,
        resume_text: str,
        resume_id: int | None,
        questions_json: str,
        current_index: int,
        status: str,
    ) -> None:
        key = _SESSION_KEY.format(session_id=session_id)
        mapping = {
            _FIELD_RESUME_TEXT: resume_text,
            _FIELD_RESUME_ID: str(resume_id) if resume_id is not None else "",
            _FIELD_QUESTIONS_JSON: questions_json,
            _FIELD_CURRENT_INDEX: str(current_index),
            _FIELD_STATUS: status,
        }
        await self._redis.hset(key, mapping)
        await self._redis.expire(key, self._ttl)
        if resume_id is not None and status in _UNFINISHED_STATUSES:
            await self._set_unfinished_mapping(resume_id, session_id)

    async def get_session(self, session_id: str) -> CachedSession | None:
        key = _SESSION_KEY.format(session_id=session_id)
        raw = await self._redis.hgetall(key)
        if not raw:
            return None
        return self._parse_cached_session(session_id, raw)

    async def update_questions(self, session_id: str, questions_json: str) -> None:
        key = _SESSION_KEY.format(session_id=session_id)
        await self._redis.hset(key, {_FIELD_QUESTIONS_JSON: questions_json})
        await self._redis.expire(key, self._ttl)

    async def update_current_index(self, session_id: str, index: int) -> None:
        key = _SESSION_KEY.format(session_id=session_id)
        await self._redis.hset(key, {_FIELD_CURRENT_INDEX: str(index)})
        await self._redis.expire(key, self._ttl)

    async def update_status(self, session_id: str, status: str) -> None:
        key = _SESSION_KEY.format(session_id=session_id)
        await self._redis.hset(key, {_FIELD_STATUS: status})
        await self._redis.expire(key, self._ttl)

    async def refresh_ttl(self, session_id: str) -> None:
        key = _SESSION_KEY.format(session_id=session_id)
        await self._redis.expire(key, self._ttl)

    async def find_unfinished_session_id(self, resume_id: int) -> str | None:
        key = _UNFINISHED_KEY.format(resume_id=resume_id)
        return await self._redis.get(key)

    async def delete_session(self, session_id: str) -> None:
        key = _SESSION_KEY.format(session_id=session_id)
        await self._redis.delete(key)

    async def delete_unfinished_mapping(self, resume_id: int) -> None:
        key = _UNFINISHED_KEY.format(resume_id=resume_id)
        await self._redis.delete(key)

    async def _set_unfinished_mapping(self, resume_id: int, session_id: str) -> None:
        key = _UNFINISHED_KEY.format(resume_id=resume_id)
        await self._redis.set(key, session_id, ex=self._ttl)

    def _parse_cached_session(self, session_id: str, raw: dict[str, str]) -> CachedSession:
        resume_id_str = raw.get(_FIELD_RESUME_ID, "")
        resume_id = int(resume_id_str) if resume_id_str else None
        return CachedSession(
            session_id=session_id,
            resume_text=raw.get(_FIELD_RESUME_TEXT, ""),
            resume_id=resume_id,
            questions_json=raw.get(_FIELD_QUESTIONS_JSON, "[]"),
            current_index=int(raw.get(_FIELD_CURRENT_INDEX, "0")),
            status=raw.get(_FIELD_STATUS, "CREATED"),
        )
