from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.entities.task_status import AsyncTaskStatus
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.constants import RESUME_ANALYZE
from app.infrastructure.tasks.resume_analyze_producer import AnalyzeStreamProducer, ResumeAnalyzePayload


def _make_session_factory(session: AsyncMock) -> MagicMock:
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


@pytest.fixture()
def mock_redis() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def repository() -> MagicMock:
    repo = MagicMock()
    repo.get_by_id = AsyncMock()
    repo.update_analyze_status = AsyncMock()
    return repo


@pytest.fixture()
def producer(mock_redis: AsyncMock, repository: MagicMock) -> AnalyzeStreamProducer:
    session = AsyncMock()
    session_factory = _make_session_factory(session)
    return AnalyzeStreamProducer(
        redis_client=RedisClient(mock_redis),
        config=RESUME_ANALYZE,
        session_factory=session_factory,
        repository=repository,
    )


class TestBuildMessage:
    def test_includes_resume_id_and_retry_count(self, producer: AnalyzeStreamProducer) -> None:
        msg = producer.build_message(ResumeAnalyzePayload(resume_id=42))

        assert msg["resumeId"] == "42"
        assert msg["retryCount"] == "0"


class TestPayloadIdentifier:
    def test_includes_resume_id(self, producer: AnalyzeStreamProducer) -> None:
        assert producer.payload_identifier(ResumeAnalyzePayload(resume_id=7)) == "resumeId=7"


class TestTaskDisplayName:
    def test_returns_chinese_name(self, producer: AnalyzeStreamProducer) -> None:
        assert producer.task_display_name() == "简历分析"


class TestOnSendFailed:
    async def test_updates_resume_status_to_failed(
        self, producer: AnalyzeStreamProducer, repository: MagicMock
    ) -> None:
        from app.infrastructure.db.models.resume import Resume

        resume = Resume(id=1, file_hash="h", original_filename="x.pdf", analyze_status="PENDING")
        repository.get_by_id.return_value = resume

        await producer.on_send_failed(ResumeAnalyzePayload(resume_id=1), "任务入队失败: Redis down")

        repository.update_analyze_status.assert_awaited_once()
        args = repository.update_analyze_status.call_args.args
        assert args[2] == AsyncTaskStatus.FAILED.value
        assert "Redis down" in args[3]

    async def test_skips_when_resume_not_found(self, producer: AnalyzeStreamProducer, repository: MagicMock) -> None:
        repository.get_by_id.return_value = None

        await producer.on_send_failed(ResumeAnalyzePayload(resume_id=999), "error")

        repository.update_analyze_status.assert_not_awaited()

    async def test_truncates_long_error(self, producer: AnalyzeStreamProducer, repository: MagicMock) -> None:
        from app.infrastructure.db.models.resume import Resume

        resume = Resume(id=1, file_hash="h", original_filename="x.pdf", analyze_status="PENDING")
        repository.get_by_id.return_value = resume
        long_error = "x" * 600

        await producer.on_send_failed(ResumeAnalyzePayload(resume_id=1), long_error)

        args = repository.update_analyze_status.call_args.args
        assert len(args[3]) <= 500


class TestSendTaskIntegration:
    async def test_sends_message_via_redis_xadd(self, producer: AnalyzeStreamProducer, mock_redis: AsyncMock) -> None:
        mock_redis.xadd.return_value = "100-0"

        msg_id = await producer.send_task(ResumeAnalyzePayload(resume_id=5))

        assert msg_id == "100-0"
        mock_redis.xadd.assert_awaited_once()
        call_args = mock_redis.xadd.call_args
        assert call_args.args[0] == "resume:analyze:stream"
