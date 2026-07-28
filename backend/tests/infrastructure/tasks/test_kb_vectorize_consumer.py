from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.entities.task_status import AsyncTaskStatus
from app.infrastructure.db.models.knowledge_base import KnowledgeBaseDocument
from app.infrastructure.redis.client import RedisClient
from app.infrastructure.tasks.constants import KB_VECTORIZE
from app.infrastructure.tasks.kb_vectorize_consumer import VectorizeStreamConsumer
from app.infrastructure.tasks.kb_vectorize_producer import KbVectorizePayload

_DOC_ID = 11


def _make_document(**overrides: object) -> KnowledgeBaseDocument:
    defaults: dict[str, object] = {
        "id": _DOC_ID,
        "knowledge_base_id": 1,
        "file_hash": "h",
        "original_filename": "doc.pdf",
        "file_size": 2048,
        "content_type": "application/pdf",
        "storage_key": "doc-k",
        "storage_url": "doc-u",
        "content_text": "正文",
        "chunk_count": 3,
        "vector_status": AsyncTaskStatus.PENDING.value,
        "vector_error": None,
        "uploaded_at": None,
    }
    defaults.update(overrides)
    return KnowledgeBaseDocument(**defaults)


def _make_session_factory() -> tuple[MagicMock, AsyncMock]:
    session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


def _make_consumer() -> tuple[VectorizeStreamConsumer, dict[str, MagicMock]]:
    factory, _session = _make_session_factory()
    repository = MagicMock()
    repository.get_by_id = AsyncMock()
    repository.update_vector_status = AsyncMock()
    repository.mark_vectorized = AsyncMock()

    vector_repository = MagicMock()
    vector_repository.insert_pending = AsyncMock(return_value=2)
    vector_repository.promote_vector_job = AsyncMock(return_value=2)
    vector_repository.delete_by_knowledge_base_id = AsyncMock(return_value=0)
    vector_repository.delete_by_document_id = AsyncMock(return_value=0)
    vector_repository.delete_by_vector_job_id = AsyncMock(return_value=0)

    chunker = MagicMock()
    chunker.split = MagicMock(return_value=["chunk-a", "chunk-b"])

    embeddings = MagicMock()
    embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 1024, [0.2] * 1024])
    llm_registry = MagicMock()
    llm_registry.get_default_embeddings = AsyncMock(return_value=embeddings)

    redis_mock = AsyncMock()
    document_repository = MagicMock()
    document_repository.get_by_id = AsyncMock(return_value=_make_document())
    document_repository.list_by_kb = AsyncMock(return_value=[])
    document_repository.list_statuses_by_kb = AsyncMock(return_value=[])
    document_repository.sum_chunk_count_by_kb = AsyncMock(return_value=0)
    document_repository.update_vector_status = AsyncMock()
    document_repository.mark_vectorized = AsyncMock()
    consumer = VectorizeStreamConsumer(
        redis_client=RedisClient(redis_mock),
        config=KB_VECTORIZE,
        session_factory=factory,
        repository=repository,
        vector_repository=vector_repository,
        chunker=chunker,
        llm_registry=llm_registry,
        document_repository=document_repository,
    )
    return consumer, {
        "repository": repository,
        "vector_repository": vector_repository,
        "chunker": chunker,
        "embeddings": embeddings,
        "llm_registry": llm_registry,
        "document_repository": document_repository,
        "redis": redis_mock,
    }


def _payload(**overrides: int) -> KbVectorizePayload:
    defaults = {"knowledge_base_id": 1, "document_id": _DOC_ID}
    defaults.update(overrides)
    return KbVectorizePayload(**defaults)


class TestParsePayload:
    def test_parses_both_ids(self) -> None:
        consumer, _ = _make_consumer()
        payload = consumer.parse_payload("100-0", {b"knowledgeBaseId": b"42", b"documentId": b"7", b"retryCount": b"0"})
        assert payload == KbVectorizePayload(knowledge_base_id=42, document_id=7)

    def test_returns_none_when_missing_kb_id(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.parse_payload("100-0", {b"retryCount": b"0"}) is None

    def test_returns_none_when_invalid_kb_id(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.parse_payload("100-0", {b"knowledgeBaseId": b"abc"}) is None

    def test_returns_none_when_missing_document_id(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.parse_payload("100-0", {b"knowledgeBaseId": b"42", b"retryCount": b"0"}) is None

    def test_returns_none_when_invalid_document_id(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.parse_payload("100-0", {b"knowledgeBaseId": b"42", b"documentId": b"abc"}) is None


class TestPayloadIdentifier:
    def test_includes_both_ids(self) -> None:
        consumer, _ = _make_consumer()
        assert consumer.payload_identifier(_payload()) == f"knowledgeBaseId=1, documentId={_DOC_ID}"


class TestMarkProcessing:
    async def test_sets_processing(self) -> None:
        consumer, mocks = _make_consumer()

        await consumer.mark_processing(_payload())

        args = mocks["document_repository"].update_vector_status.call_args.args
        assert args[2] == AsyncTaskStatus.PROCESSING.value

    async def test_skips_when_completed(self) -> None:
        consumer, mocks = _make_consumer()
        mocks["document_repository"].get_by_id.return_value = _make_document(
            vector_status=AsyncTaskStatus.COMPLETED.value
        )

        await consumer.mark_processing(_payload())

        mocks["document_repository"].update_vector_status.assert_not_awaited()

    async def test_skips_when_deleted(self) -> None:
        consumer, mocks = _make_consumer()
        mocks["document_repository"].get_by_id.return_value = None

        await consumer.mark_processing(_payload())

        mocks["document_repository"].update_vector_status.assert_not_awaited()


class TestProcessBusiness:
    async def test_two_phase_commit_happy_path(self) -> None:
        consumer, mocks = _make_consumer()

        await consumer.process_business(_payload())

        mocks["embeddings"].aembed_documents.assert_awaited_once()
        mocks["vector_repository"].insert_pending.assert_awaited_once()
        mocks["vector_repository"].delete_by_document_id.assert_awaited_once()
        mocks["vector_repository"].promote_vector_job.assert_awaited_once()
        mocks["document_repository"].mark_vectorized.assert_awaited_once()
        assert mocks["document_repository"].mark_vectorized.call_args.args[3] == 2

    async def test_skips_when_completed(self) -> None:
        consumer, mocks = _make_consumer()
        mocks["document_repository"].get_by_id.return_value = _make_document(
            vector_status=AsyncTaskStatus.COMPLETED.value
        )

        await consumer.process_business(_payload())

        mocks["vector_repository"].insert_pending.assert_not_awaited()

    async def test_skips_when_deleted(self) -> None:
        consumer, mocks = _make_consumer()
        mocks["document_repository"].get_by_id.return_value = None

        await consumer.process_business(_payload())

        mocks["vector_repository"].insert_pending.assert_not_awaited()

    async def test_empty_chunks_marks_zero(self) -> None:
        consumer, mocks = _make_consumer()
        mocks["document_repository"].get_by_id.return_value = _make_document(content_text="")
        mocks["chunker"].split.return_value = []

        await consumer.process_business(_payload())

        mocks["vector_repository"].insert_pending.assert_not_awaited()
        mocks["vector_repository"].delete_by_document_id.assert_awaited_once()
        assert mocks["document_repository"].mark_vectorized.call_args.args[3] == 0

    async def test_cleans_pending_on_failure(self) -> None:
        consumer, mocks = _make_consumer()
        mocks["vector_repository"].promote_vector_job.side_effect = RuntimeError("db down")

        with pytest.raises(RuntimeError):
            await consumer.process_business(_payload())

        mocks["vector_repository"].delete_by_vector_job_id.assert_awaited_once()


class TestMarkCompletedFailed:
    async def test_mark_completed(self) -> None:
        consumer, mocks = _make_consumer()

        await consumer.mark_completed(_payload())

        assert mocks["document_repository"].update_vector_status.call_args.args[2] == AsyncTaskStatus.COMPLETED.value

    async def test_mark_failed(self) -> None:
        consumer, mocks = _make_consumer()

        await consumer.mark_failed(_payload(), "boom")

        args = mocks["document_repository"].update_vector_status.call_args.args
        assert args[2] == AsyncTaskStatus.FAILED.value
        assert args[3] == "boom"


class TestRetryMessage:
    async def test_reenqueues_with_retry_count(self) -> None:
        consumer, mocks = _make_consumer()
        redis = mocks["redis"]

        await consumer.retry_message(_payload(knowledge_base_id=9), 2)

        redis.xadd.assert_awaited_once()
        sent = redis.xadd.call_args.args[1]
        assert sent["knowledgeBaseId"] == "9"
        assert sent["documentId"] == str(_DOC_ID)
        assert sent["retryCount"] == "2"
