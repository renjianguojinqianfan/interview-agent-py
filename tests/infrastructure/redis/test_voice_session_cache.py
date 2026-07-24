from unittest.mock import AsyncMock

import pytest

from app.infrastructure.redis.voice_session_cache import (
    CachedVoiceSession,
    VoiceInterviewSessionCache,
)

_TTL = 999


@pytest.fixture()
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def cache(mock_redis: AsyncMock) -> VoiceInterviewSessionCache:
    return VoiceInterviewSessionCache(mock_redis, ttl=_TTL)


def _make_snapshot(**overrides: object) -> CachedVoiceSession:
    defaults: dict[str, object] = {
        "session_id": "5",
        "user_id": "u1",
        "role_type": "interviewer",
        "skill_id": "java-backend",
        "difficulty": "mid",
        "current_phase": "OPENING",
        "status": "IN_PROGRESS",
        "resume_id": 42,
        "llm_provider": "dashscope",
    }
    defaults.update(overrides)
    return CachedVoiceSession(**defaults)  # type: ignore[arg-type]


def _full_hash() -> dict[str, str]:
    return {
        "userId": "u1",
        "roleType": "interviewer",
        "skillId": "java-backend",
        "difficulty": "mid",
        "currentPhase": "OPENING",
        "status": "IN_PROGRESS",
        "resumeId": "42",
        "llmProvider": "dashscope",
    }


class TestSaveSession:
    async def test_writes_hash_and_sets_ttl(self, cache: VoiceInterviewSessionCache, mock_redis: AsyncMock) -> None:
        await cache.save_session(_make_snapshot())
        mock_redis.hset.assert_awaited_once()
        key, mapping = mock_redis.hset.call_args.args
        assert key == "voice:session:5"
        assert mapping["resumeId"] == "42"
        assert mapping["llmProvider"] == "dashscope"
        mock_redis.expire.assert_awaited_once_with("voice:session:5", _TTL)

    async def test_serializes_none_optionals_as_empty_string(
        self, cache: VoiceInterviewSessionCache, mock_redis: AsyncMock
    ) -> None:
        await cache.save_session(_make_snapshot(resume_id=None, llm_provider=None))
        _key, mapping = mock_redis.hset.call_args.args
        assert mapping["resumeId"] == ""
        assert mapping["llmProvider"] == ""


class TestGetSession:
    async def test_reconstructs_all_fields(self, cache: VoiceInterviewSessionCache, mock_redis: AsyncMock) -> None:
        mock_redis.hgetall.return_value = _full_hash()
        result = await cache.get_session(5)
        assert result is not None
        assert result.session_id == "5"
        assert result.user_id == "u1"
        assert result.current_phase == "OPENING"
        assert result.resume_id == 42
        assert result.llm_provider == "dashscope"
        mock_redis.hgetall.assert_awaited_once_with("voice:session:5")

    async def test_empty_optionals_become_none(self, cache: VoiceInterviewSessionCache, mock_redis: AsyncMock) -> None:
        raw = _full_hash()
        raw["resumeId"] = ""
        raw["llmProvider"] = ""
        mock_redis.hgetall.return_value = raw
        result = await cache.get_session(5)
        assert result is not None
        assert result.resume_id is None
        assert result.llm_provider is None

    async def test_returns_none_when_missing(self, cache: VoiceInterviewSessionCache, mock_redis: AsyncMock) -> None:
        mock_redis.hgetall.return_value = {}
        assert await cache.get_session(999) is None


class TestDeleteSession:
    async def test_deletes_key(self, cache: VoiceInterviewSessionCache, mock_redis: AsyncMock) -> None:
        await cache.delete_session(5)
        mock_redis.delete.assert_awaited_once_with("voice:session:5")


class TestRefreshTtl:
    async def test_calls_expire_with_ttl(self, cache: VoiceInterviewSessionCache, mock_redis: AsyncMock) -> None:
        await cache.refresh_ttl(5)
        mock_redis.expire.assert_awaited_once_with("voice:session:5", _TTL)
