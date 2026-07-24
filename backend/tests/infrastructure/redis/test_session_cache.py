from unittest.mock import AsyncMock

import pytest

from app.infrastructure.redis.client import RedisClient
from app.infrastructure.redis.session_cache import CachedSession, InterviewSessionCache


@pytest.fixture()
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def cache(mock_redis: AsyncMock) -> InterviewSessionCache:
    return InterviewSessionCache(RedisClient(mock_redis))


class TestSaveSession:
    async def test_saves_hash_and_sets_ttl(self, cache: InterviewSessionCache, mock_redis: AsyncMock) -> None:
        await cache.save_session(
            session_id="sess123",
            resume_text="简历内容",
            resume_id=42,
            questions_json="[]",
            current_index=0,
            status="CREATED",
        )
        mock_redis.hset.assert_awaited_once()
        mock_redis.expire.assert_awaited()
        args = mock_redis.hset.call_args.args
        assert args[0] == b"interview:session:sess123"

    async def test_sets_unfinished_mapping_when_resume_id_and_unfinished(
        self, cache: InterviewSessionCache, mock_redis: AsyncMock
    ) -> None:
        await cache.save_session(
            session_id="sess123",
            resume_text="",
            resume_id=42,
            questions_json="[]",
            current_index=0,
            status="CREATED",
        )
        mock_redis.set.assert_awaited()
        set_args = mock_redis.set.call_args.args
        assert set_args[0] == b"interview:resume:42:unfinished"
        assert set_args[1] == b"sess123"

    async def test_no_unfinished_mapping_when_no_resume_id(
        self, cache: InterviewSessionCache, mock_redis: AsyncMock
    ) -> None:
        await cache.save_session(
            session_id="sess123",
            resume_text="",
            resume_id=None,
            questions_json="[]",
            current_index=0,
            status="CREATED",
        )
        mock_redis.set.assert_not_awaited()

    async def test_no_unfinished_mapping_when_completed(
        self, cache: InterviewSessionCache, mock_redis: AsyncMock
    ) -> None:
        await cache.save_session(
            session_id="sess123",
            resume_text="",
            resume_id=42,
            questions_json="[]",
            current_index=5,
            status="COMPLETED",
        )
        mock_redis.set.assert_not_awaited()


class TestGetSession:
    async def test_returns_cached_session(self, cache: InterviewSessionCache, mock_redis: AsyncMock) -> None:
        mock_redis.hgetall.return_value = {
            b"resumeText": b"resume content",
            b"resumeId": b"42",
            b"questionsJson": b"[]",
            b"currentIndex": b"0",
            b"status": b"CREATED",
        }
        result = await cache.get_session("sess123")
        assert result is not None
        assert result.session_id == "sess123"
        assert result.resume_text == "resume content"
        assert result.resume_id == 42
        assert result.current_index == 0
        assert result.status == "CREATED"

    async def test_returns_none_when_missing(self, cache: InterviewSessionCache, mock_redis: AsyncMock) -> None:
        mock_redis.hgetall.return_value = {}
        assert await cache.get_session("missing") is None

    async def test_handles_empty_resume_id(self, cache: InterviewSessionCache, mock_redis: AsyncMock) -> None:
        mock_redis.hgetall.return_value = {
            b"resumeText": b"",
            b"resumeId": b"",
            b"questionsJson": b"[]",
            b"currentIndex": b"0",
            b"status": b"CREATED",
        }
        result = await cache.get_session("sess123")
        assert result is not None
        assert result.resume_id is None


class TestUpdateQuestions:
    async def test_updates_questions_field_and_refreshes_ttl(
        self, cache: InterviewSessionCache, mock_redis: AsyncMock
    ) -> None:
        await cache.update_questions("sess123", '[{"question":"Q1"}]')
        mock_redis.hset.assert_awaited_once()
        mock_redis.expire.assert_awaited_once()


class TestUpdateCurrentIndex:
    async def test_updates_index_field(self, cache: InterviewSessionCache, mock_redis: AsyncMock) -> None:
        await cache.update_current_index("sess123", 3)
        mock_redis.hset.assert_awaited_once()
        mock_redis.expire.assert_awaited_once()


class TestUpdateStatus:
    async def test_updates_status_field(self, cache: InterviewSessionCache, mock_redis: AsyncMock) -> None:
        await cache.update_status("sess123", "IN_PROGRESS")
        mock_redis.hset.assert_awaited_once()
        mock_redis.expire.assert_awaited_once()


class TestRefreshTtl:
    async def test_calls_expire(self, cache: InterviewSessionCache, mock_redis: AsyncMock) -> None:
        await cache.refresh_ttl("sess123")
        mock_redis.expire.assert_awaited_once()
        assert mock_redis.expire.call_args.args[0] == b"interview:session:sess123"


class TestFindUnfinishedSessionId:
    async def test_returns_session_id(self, cache: InterviewSessionCache, mock_redis: AsyncMock) -> None:
        mock_redis.get.return_value = b"sess123"
        assert await cache.find_unfinished_session_id(42) == "sess123"

    async def test_returns_none_when_missing(self, cache: InterviewSessionCache, mock_redis: AsyncMock) -> None:
        mock_redis.get.return_value = None
        assert await cache.find_unfinished_session_id(42) is None


class TestDeleteSession:
    async def test_deletes_session_key(self, cache: InterviewSessionCache, mock_redis: AsyncMock) -> None:
        await cache.delete_session("sess123")
        mock_redis.delete.assert_awaited_once_with(b"interview:session:sess123")


class TestDeleteUnfinishedMapping:
    async def test_deletes_unfinished_key(self, cache: InterviewSessionCache, mock_redis: AsyncMock) -> None:
        await cache.delete_unfinished_mapping(42)
        mock_redis.delete.assert_awaited_once_with(b"interview:resume:42:unfinished")


class TestCachedSessionDataclass:
    def test_construction(self) -> None:
        cs = CachedSession(
            session_id="sess123",
            resume_text="text",
            resume_id=42,
            questions_json="[]",
            current_index=0,
            status="CREATED",
        )
        assert cs.session_id == "sess123"
        assert cs.resume_id == 42
