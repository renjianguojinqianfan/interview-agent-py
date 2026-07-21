"""语音面试会话 Redis 缓存：create/resume 写入、end/pause 失效、TTL 1 小时。

为 #15 WebSocket 握手提供快速会话恢复入口；#14 REST 侧负责写入与失效。
Redis 连接 decode_responses=False，所有 key/value 在 RedisClient 层做 bytes<->str 转换。
"""

from dataclasses import dataclass

from app.domain.entities.voice_interview import VOICE_SESSION_TTL_SECONDS
from app.infrastructure.redis.client import RedisClient

_SESSION_KEY = "voice:session:{session_id}"

_FIELD_USER_ID = "userId"
_FIELD_ROLE_TYPE = "roleType"
_FIELD_SKILL_ID = "skillId"
_FIELD_DIFFICULTY = "difficulty"
_FIELD_CURRENT_PHASE = "currentPhase"
_FIELD_STATUS = "status"
_FIELD_RESUME_ID = "resumeId"
_FIELD_LLM_PROVIDER = "llmProvider"


@dataclass(frozen=True)
class CachedVoiceSession:
    """Redis 缓存的语音会话快照。session_id 为数字主键的字符串形式。"""

    session_id: str
    user_id: str
    role_type: str
    skill_id: str
    difficulty: str
    current_phase: str
    status: str
    resume_id: int | None
    llm_provider: str | None


class VoiceInterviewSessionCache:
    """语音会话缓存。Redis 失败仅 warn，不阻塞业务。"""

    def __init__(
        self,
        redis_client: RedisClient,
        ttl: int = VOICE_SESSION_TTL_SECONDS,
    ) -> None:
        self._redis = redis_client
        self._ttl = ttl

    async def save_session(self, snapshot: CachedVoiceSession) -> None:
        key = _SESSION_KEY.format(session_id=snapshot.session_id)
        mapping = {
            _FIELD_USER_ID: snapshot.user_id,
            _FIELD_ROLE_TYPE: snapshot.role_type,
            _FIELD_SKILL_ID: snapshot.skill_id,
            _FIELD_DIFFICULTY: snapshot.difficulty,
            _FIELD_CURRENT_PHASE: snapshot.current_phase,
            _FIELD_STATUS: snapshot.status,
            _FIELD_RESUME_ID: str(snapshot.resume_id) if snapshot.resume_id is not None else "",
            _FIELD_LLM_PROVIDER: snapshot.llm_provider or "",
        }
        await self._redis.hset(key, mapping)
        await self._redis.expire(key, self._ttl)

    async def get_session(self, session_id: int) -> CachedVoiceSession | None:
        key = _SESSION_KEY.format(session_id=session_id)
        raw = await self._redis.hgetall(key)
        if not raw:
            return None
        return self._parse_cached_session(str(session_id), raw)

    async def delete_session(self, session_id: int) -> None:
        key = _SESSION_KEY.format(session_id=session_id)
        await self._redis.delete(key)

    async def refresh_ttl(self, session_id: int) -> None:
        key = _SESSION_KEY.format(session_id=session_id)
        await self._redis.expire(key, self._ttl)

    def _parse_cached_session(self, session_id: str, raw: dict[str, str]) -> CachedVoiceSession:
        resume_id_str = raw.get(_FIELD_RESUME_ID, "")
        resume_id = int(resume_id_str) if resume_id_str else None
        llm_provider = raw.get(_FIELD_LLM_PROVIDER, "")
        return CachedVoiceSession(
            session_id=session_id,
            user_id=raw.get(_FIELD_USER_ID, ""),
            role_type=raw.get(_FIELD_ROLE_TYPE, ""),
            skill_id=raw.get(_FIELD_SKILL_ID, ""),
            difficulty=raw.get(_FIELD_DIFFICULTY, ""),
            current_phase=raw.get(_FIELD_CURRENT_PHASE, ""),
            status=raw.get(_FIELD_STATUS, ""),
            resume_id=resume_id,
            llm_provider=llm_provider or None,
        )
