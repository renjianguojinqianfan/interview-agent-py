from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.entities.task_status import AsyncTaskStatus
from app.infrastructure.db.models.knowledge_base import KnowledgeBase
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.constants import KB_VECTORIZE
from app.infrastructure.tasks.kb_vectorize_producer import KbVectorizePayload, VectorizeStreamProducer


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
    repo.update_vector_status = AsyncMock()
    return repo


@pytest.fixture()
def producer(mock_redis: AsyncMock, repository: MagicMock) -> VectorizeStreamProducer:
    session_factory = _make_session_factory(AsyncMock())
    return VectorizeStreamProducer(
        redis_client=RedisClient(mock_redis),
        config=KB_VECTORIZE,
        session_factory=session_factory,
        repository=repository,
    )


class TestBuildMessage:
    def test_includes_knowledge_base_id_and_retry_count(self, producer: VectorizeStreamProducer) -> None:
        msg = producer.build_message(KbVectorizePayload(knowledge_base_id=42))

        assert msg["knowledgeBaseId"] == "42"
        assert msg["retryCount"] == "0"


class TestPayloadIdentifier:
    def test_includes_knowledge_base_id(self, producer: VectorizeStreamProducer) -> None:
        assert producer.payload_identifier(KbVectorizePayload(knowledge_base_id=7)) == "knowledgeBaseId=7"


class TestTaskDisplayName:
    def test_returns_chinese_name(self, producer: VectorizeStreamProducer) -> None:
        assert producer.task_display_name() == "知识库向量化"


class TestOnSendFailed:
    async def test_updates_status_to_failed(self, producer: VectorizeStreamProducer, repository: MagicMock) -> None:
        kb = KnowledgeBase(id=1, file_hash="h", original_filename="x.pdf", vector_status="PENDING")
        repository.get_by_id.return_value = kb

        await producer.on_send_failed(KbVectorizePayload(knowledge_base_id=1), "任务入队失败: Redis down")

        repository.update_vector_status.assert_awaited_once()
        args = repository.update_vector_status.call_args.args
        assert args[2] == AsyncTaskStatus.FAILED.value
        assert "Redis down" in args[3]

    async def test_skips_when_not_found(self, producer: VectorizeStreamProducer, repository: MagicMock) -> None:
        repository.get_by_id.return_value = None

        await producer.on_send_failed(KbVectorizePayload(knowledge_base_id=999), "error")

        repository.update_vector_status.assert_not_awaited()

    async def test_truncates_long_error(self, producer: VectorizeStreamProducer, repository: MagicMock) -> None:
        kb = KnowledgeBase(id=1, file_hash="h", original_filename="x.pdf", vector_status="PENDING")
        repository.get_by_id.return_value = kb

        await producer.on_send_failed(KbVectorizePayload(knowledge_base_id=1), "x" * 600)

        args = repository.update_vector_status.call_args.args
        assert len(args[3]) <= 500


class TestSendTaskIntegration:
    async def test_sends_message_via_redis_xadd(self, producer: VectorizeStreamProducer, mock_redis: AsyncMock) -> None:
        mock_redis.xadd.return_value = "100-0"

        msg_id = await producer.send_task(KbVectorizePayload(knowledge_base_id=5))

        assert msg_id == "100-0"
        mock_redis.xadd.assert_awaited_once()
        assert mock_redis.xadd.call_args.args[0] == "knowledgebase:vectorize:stream"
