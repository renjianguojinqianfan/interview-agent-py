from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.entities.task_status import AsyncTaskStatus
from app.infrastructure.db.models.interview import InterviewSession as InterviewSessionORM
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.constants import INTERVIEW_EVALUATE
from app.infrastructure.tasks.interview_evaluate_producer import EvaluatePayload, EvaluateStreamProducer


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
    repo.find_by_session_id = AsyncMock()
    repo.update_evaluate_status = AsyncMock()
    return repo


@pytest.fixture()
def producer(mock_redis: AsyncMock, repository: MagicMock) -> EvaluateStreamProducer:
    session = AsyncMock()
    session_factory = _make_session_factory(session)
    return EvaluateStreamProducer(
        redis_client=RedisClient(mock_redis),
        config=INTERVIEW_EVALUATE,
        session_factory=session_factory,
        repository=repository,
    )


def _make_session_orm(**overrides: object) -> InterviewSessionORM:
    defaults: dict[str, object] = {
        "session_id": "abc1234567890def",
        "skill_id": "java-backend",
        "difficulty": "mid",
        "total_questions": 5,
        "current_question_index": 0,
        "status": "COMPLETED",
    }
    defaults.update(overrides)
    return InterviewSessionORM(**defaults)  # type: ignore[arg-type]


class TestBuildMessage:
    def test_includes_session_id_and_retry_count(self, producer: EvaluateStreamProducer) -> None:
        msg = producer.build_message(EvaluatePayload(session_id="sess123"))
        assert msg["sessionId"] == "sess123"
        assert msg["retryCount"] == "0"


class TestPayloadIdentifier:
    def test_includes_session_id(self, producer: EvaluateStreamProducer) -> None:
        assert producer.payload_identifier(EvaluatePayload(session_id="sess456")) == "sessionId=sess456"


class TestTaskDisplayName:
    def test_returns_chinese_name(self, producer: EvaluateStreamProducer) -> None:
        assert producer.task_display_name() == "面试评估"


class TestOnSendFailed:
    async def test_updates_session_evaluate_status_to_failed(
        self, producer: EvaluateStreamProducer, repository: MagicMock
    ) -> None:
        orm = _make_session_orm()
        repository.find_by_session_id.return_value = orm

        await producer.on_send_failed(EvaluatePayload(session_id="sess123"), "任务入队失败: Redis down")

        repository.update_evaluate_status.assert_awaited_once()
        args = repository.update_evaluate_status.call_args.args
        assert args[2] == AsyncTaskStatus.FAILED.value
        assert "Redis down" in args[3]

    async def test_skips_when_session_not_found(self, producer: EvaluateStreamProducer, repository: MagicMock) -> None:
        repository.find_by_session_id.return_value = None

        await producer.on_send_failed(EvaluatePayload(session_id="missing"), "error")

        repository.update_evaluate_status.assert_not_awaited()

    async def test_truncates_long_error(self, producer: EvaluateStreamProducer, repository: MagicMock) -> None:
        orm = _make_session_orm()
        repository.find_by_session_id.return_value = orm
        long_error = "x" * 600

        await producer.on_send_failed(EvaluatePayload(session_id="sess123"), long_error)

        args = repository.update_evaluate_status.call_args.args
        assert len(args[3]) <= 500


class TestSendTaskIntegration:
    async def test_sends_message_via_redis_xadd(self, producer: EvaluateStreamProducer, mock_redis: AsyncMock) -> None:
        mock_redis.xadd.return_value = "100-0"

        msg_id = await producer.send_task(EvaluatePayload(session_id="sess5"))

        assert msg_id == "100-0"
        mock_redis.xadd.assert_awaited_once()
        call_args = mock_redis.xadd.call_args
        assert call_args.args[0] == "interview:evaluate:stream"
