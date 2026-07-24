from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.db.models.knowledge_base import KnowledgeBase
from app.infrastructure.db.repositories.knowledge_base_repository import KnowledgeBaseRepository


@pytest.fixture()
def session() -> MagicMock:
    mock = MagicMock()
    mock.execute = AsyncMock()
    mock.flush = AsyncMock()
    mock.delete = AsyncMock()
    return mock


@pytest.fixture()
def repo() -> KnowledgeBaseRepository:
    return KnowledgeBaseRepository()


def _make_kb(**overrides: object) -> KnowledgeBase:
    defaults: dict[str, object] = {
        "id": 1,
        "file_hash": "hash1",
        "original_filename": "doc.pdf",
    }
    defaults.update(overrides)
    return KnowledgeBase(**defaults)  # type: ignore[arg-type]


def _scalar_one(session: AsyncMock, value: object) -> None:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = value
    session.execute.return_value = mock_result


def _scalars_all(session: AsyncMock, values: list[object]) -> None:
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = values
    session.execute.return_value = mock_result


def _scalar(session: AsyncMock, value: object) -> None:
    mock_result = MagicMock()
    mock_result.scalar.return_value = value
    session.execute.return_value = mock_result


class TestFindByHash:
    async def test_found(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        kb = _make_kb()
        _scalar_one(session, kb)
        assert await repo.find_by_hash(session, "hash1") is kb

    async def test_none(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        _scalar_one(session, None)
        assert await repo.find_by_hash(session, "missing") is None


class TestGetById:
    async def test_found(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        kb = _make_kb()
        _scalar_one(session, kb)
        assert await repo.get_by_id(session, 1) is kb


class TestSave:
    async def test_adds_and_flushes(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        kb = _make_kb()
        result = await repo.save(session, kb)
        session.add.assert_called_once_with(kb)
        session.flush.assert_awaited_once()
        assert result is kb


class TestListAll:
    async def test_no_filter(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        kbs = [_make_kb(id=1), _make_kb(id=2, file_hash="h2")]
        _scalars_all(session, kbs)
        assert await repo.list_all(session) == kbs

    async def test_with_vector_status(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        kbs = [_make_kb(vector_status="DONE")]
        _scalars_all(session, kbs)
        assert await repo.list_all(session, vector_status="DONE") == kbs


class TestListByCategory:
    async def test_specific_category(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        kbs = [_make_kb(category="JAVA")]
        _scalars_all(session, kbs)
        assert await repo.list_by_category(session, "JAVA") == kbs

    async def test_none_category_branch(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        kbs = [_make_kb(category=None)]
        _scalars_all(session, kbs)
        assert await repo.list_by_category(session, None) == kbs


class TestListCategories:
    async def test_filters_none_values(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        _scalars_all(session, ["JAVA", None, "PYTHON"])
        assert await repo.list_categories(session) == ["JAVA", "PYTHON"]


class TestSearch:
    async def test_returns_matches(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        kbs = [_make_kb(name="Spring 指南")]
        _scalars_all(session, kbs)
        assert await repo.search(session, "Spring") == kbs


class TestCounts:
    async def test_count_all(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        _scalar(session, 7)
        assert await repo.count_all(session) == 7

    async def test_count_all_defaults_zero(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        _scalar(session, None)
        assert await repo.count_all(session) == 0

    async def test_sum_access_count(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        _scalar(session, 42)
        assert await repo.sum_access_count(session) == 42

    async def test_count_by_vector_status(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        _scalar(session, 3)
        assert await repo.count_by_vector_status(session, "DONE") == 3


class TestDelete:
    async def test_deletes(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        kb = _make_kb()
        await repo.delete(session, kb)
        session.delete.assert_awaited_once_with(kb)


class TestUpdateVectorStatus:
    async def test_sets_status_and_clears_error(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        kb = _make_kb(vector_status="PENDING")
        await repo.update_vector_status(session, kb, "DONE")
        assert kb.vector_status == "DONE"
        assert kb.vector_error is None
        session.flush.assert_awaited_once()

    async def test_sets_error(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        kb = _make_kb()
        await repo.update_vector_status(session, kb, "FAILED", "boom")
        assert kb.vector_status == "FAILED"
        assert kb.vector_error == "boom"


class TestUpdateCategory:
    async def test_updates_category(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        kb = _make_kb(category=None)
        await repo.update_category(session, kb, "PYTHON")
        assert kb.category == "PYTHON"
        session.flush.assert_awaited_once()


class TestMarkVectorized:
    async def test_sets_job_chunk_and_timestamp(self, repo: KnowledgeBaseRepository, session: AsyncMock) -> None:
        kb = _make_kb()
        await repo.mark_vectorized(session, kb, "job-123", 12)
        assert kb.vector_job_id == "job-123"
        assert kb.chunk_count == 12
        assert kb.vectorized_at is not None
        session.flush.assert_awaited_once()
