from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.db.models.llm_provider import LlmProvider
from app.infrastructure.db.repositories.llm_provider_repository import LlmProviderRepository


@pytest.fixture()
def session() -> MagicMock:
    mock = MagicMock()
    mock.execute = AsyncMock()
    mock.flush = AsyncMock()
    mock.delete = AsyncMock()
    return mock


@pytest.fixture()
def repo() -> LlmProviderRepository:
    return LlmProviderRepository()


def _make_provider(**overrides: object) -> LlmProvider:
    defaults: dict[str, object] = {
        "id": 1,
        "provider_name": "dashscope",
        "base_url": "https://example.com/v1",
        "model": "qwen-max",
    }
    defaults.update(overrides)
    return LlmProvider(**defaults)  # type: ignore[arg-type]


class TestSave:
    async def test_adds_and_flushes(self, repo: LlmProviderRepository, session: AsyncMock) -> None:
        provider = _make_provider()
        result = await repo.save(session, provider)
        session.add.assert_called_once_with(provider)
        session.flush.assert_awaited_once()
        assert result is provider


class TestGetById:
    async def test_returns_when_found(self, repo: LlmProviderRepository, session: AsyncMock) -> None:
        provider = _make_provider()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = provider
        session.execute.return_value = mock_result
        assert await repo.get_by_id(session, 1) is provider

    async def test_returns_none_when_missing(self, repo: LlmProviderRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result
        assert await repo.get_by_id(session, 999) is None


class TestGetByName:
    async def test_returns_when_found(self, repo: LlmProviderRepository, session: AsyncMock) -> None:
        provider = _make_provider(provider_name="dashscope")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = provider
        session.execute.return_value = mock_result
        assert await repo.get_by_name(session, "dashscope") is provider


class TestListAll:
    async def test_returns_all(self, repo: LlmProviderRepository, session: AsyncMock) -> None:
        providers = [_make_provider(id=1), _make_provider(id=2, provider_name="openai")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = providers
        session.execute.return_value = mock_result
        assert await repo.list_all(session) == providers


class TestDelete:
    async def test_deletes(self, repo: LlmProviderRepository, session: AsyncMock) -> None:
        provider = _make_provider()
        await repo.delete(session, provider)
        session.delete.assert_awaited_once_with(provider)


class TestExistsByName:
    async def test_true_when_count_positive(self, repo: LlmProviderRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        session.execute.return_value = mock_result
        assert await repo.exists_by_name(session, "dashscope") is True

    async def test_false_when_count_zero(self, repo: LlmProviderRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        session.execute.return_value = mock_result
        assert await repo.exists_by_name(session, "missing") is False

    async def test_false_when_scalar_none(self, repo: LlmProviderRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        session.execute.return_value = mock_result
        assert await repo.exists_by_name(session, "missing") is False
