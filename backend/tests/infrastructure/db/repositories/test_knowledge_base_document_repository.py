"""KnowledgeBaseDocumentRepository 单元测试（mock session，覆盖新增/修复方法）。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.db.repositories.knowledge_base_document_repository import KnowledgeBaseDocumentRepository


@pytest.fixture()
def session() -> MagicMock:
    mock = MagicMock()
    mock.execute = AsyncMock()
    mock.flush = AsyncMock()
    mock.delete = AsyncMock()
    return mock


@pytest.fixture()
def repo() -> KnowledgeBaseDocumentRepository:
    return KnowledgeBaseDocumentRepository()


def _scalar_one_or_none(session: AsyncMock, value: object) -> None:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = value
    session.execute.return_value = mock_result


def _scalar_one(session: AsyncMock, value: object) -> None:
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = value
    session.execute.return_value = mock_result


class TestFindFirstHashByKb:
    async def test_returns_hash_when_document_exists(
        self, session: MagicMock, repo: KnowledgeBaseDocumentRepository
    ) -> None:
        _scalar_one_or_none(session, "abc123hash")

        result = await repo.find_first_hash_by_kb(session, kb_id=1)

        assert result == "abc123hash"
        session.execute.assert_awaited_once()

    async def test_returns_none_when_no_documents(
        self, session: MagicMock, repo: KnowledgeBaseDocumentRepository
    ) -> None:
        _scalar_one_or_none(session, None)

        result = await repo.find_first_hash_by_kb(session, kb_id=99)

        assert result is None


class TestSumChunkCountByKb:
    async def test_uses_sql_aggregation_not_list_by_kb(
        self, session: MagicMock, repo: KnowledgeBaseDocumentRepository
    ) -> None:
        _scalar_one(session, 42)

        result = await repo.sum_chunk_count_by_kb(session, kb_id=1)

        assert result == 42
        session.execute.assert_awaited_once()

    async def test_returns_zero_when_no_documents(
        self, session: MagicMock, repo: KnowledgeBaseDocumentRepository
    ) -> None:
        _scalar_one(session, 0)

        result = await repo.sum_chunk_count_by_kb(session, kb_id=1)

        assert result == 0
