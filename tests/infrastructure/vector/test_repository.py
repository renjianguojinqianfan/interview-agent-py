import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.vector.repository import VectorItem, VectorRepository


@pytest.fixture()
def session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def repo() -> VectorRepository:
    return VectorRepository()


class TestVectorItem:
    def test_defaults(self) -> None:
        item = VectorItem(content="hello", embedding=[0.1, 0.2])
        assert item.content == "hello"
        assert item.embedding == [0.1, 0.2]
        assert item.metadata is None


class TestInsertPending:
    async def test_inserts_with_job_metadata(self, repo: VectorRepository, session: AsyncMock) -> None:
        items = [
            VectorItem(content="chunk1", embedding=[0.1, 0.2]),
            VectorItem(content="chunk2", embedding=[0.3, 0.4]),
        ]
        count = await repo.insert_pending(session, "job-123", 42, items)

        assert count == 2
        assert session.execute.call_count == 2

    async def test_empty_items_returns_zero(self, repo: VectorRepository, session: AsyncMock) -> None:
        count = await repo.insert_pending(session, "job-123", 42, [])
        assert count == 0
        session.execute.assert_not_called()

    async def test_preserves_extra_metadata(self, repo: VectorRepository, session: AsyncMock) -> None:
        items = [VectorItem(content="chunk", embedding=[0.1], metadata={"source": "page1"})]
        await repo.insert_pending(session, "job-1", 1, items)

        call_args = session.execute.call_args
        params = call_args.kwargs.get("parameters") or call_args.args[1]
        metadata = json.loads(params["metadata"])
        assert metadata["kb_vector_job_id"] == "job-1"
        assert metadata["kb_target_id"] == "1"
        assert metadata["source"] == "page1"


class TestPromoteVectorJob:
    async def test_returns_updated_rows(self, repo: VectorRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.rowcount = 5
        session.execute.return_value = mock_result

        count = await repo.promote_vector_job(session, 42, "job-123")
        assert count == 5

    async def test_calls_update_sql(self, repo: VectorRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.rowcount = 1
        session.execute.return_value = mock_result

        await repo.promote_vector_job(session, 42, "job-123")
        assert session.execute.called

    async def test_failure_raises_business_exception(self, repo: VectorRepository, session: AsyncMock) -> None:
        session.execute.side_effect = RuntimeError("DB error")
        with pytest.raises(BusinessException) as exc_info:
            await repo.promote_vector_job(session, 42, "job-123")
        assert exc_info.value.error_code == ErrorCode.KNOWLEDGE_BASE_VECTORIZATION_FAILED


class TestDeleteByKnowledgeBaseId:
    async def test_returns_deleted_rows(self, repo: VectorRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.rowcount = 3
        session.execute.return_value = mock_result

        count = await repo.delete_by_knowledge_base_id(session, 42)
        assert count == 3

    async def test_failure_raises(self, repo: VectorRepository, session: AsyncMock) -> None:
        session.execute.side_effect = RuntimeError("DB error")
        with pytest.raises(BusinessException) as exc_info:
            await repo.delete_by_knowledge_base_id(session, 42)
        assert exc_info.value.error_code == ErrorCode.KNOWLEDGE_BASE_DELETE_FAILED


class TestDeleteByVectorJobId:
    async def test_returns_deleted_rows(self, repo: VectorRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.rowcount = 2
        session.execute.return_value = mock_result

        count = await repo.delete_by_vector_job_id(session, "job-123")
        assert count == 2

    async def test_failure_raises(self, repo: VectorRepository, session: AsyncMock) -> None:
        session.execute.side_effect = RuntimeError("DB error")
        with pytest.raises(BusinessException) as exc_info:
            await repo.delete_by_vector_job_id(session, "job-123")
        assert exc_info.value.error_code == ErrorCode.KNOWLEDGE_BASE_VECTORIZATION_FAILED
