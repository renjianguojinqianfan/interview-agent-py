from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.db.models.llm_global_setting import LlmGlobalSetting
from app.infrastructure.db.repositories.llm_global_setting_repository import (
    LlmGlobalSettingRepository,
)


@pytest.fixture()
def session() -> MagicMock:
    mock = MagicMock()
    mock.execute = AsyncMock()
    mock.flush = AsyncMock()
    return mock


@pytest.fixture()
def repo() -> LlmGlobalSettingRepository:
    return LlmGlobalSettingRepository()


def _make_setting(**overrides: object) -> LlmGlobalSetting:
    defaults: dict[str, object] = {
        "id": LlmGlobalSetting.SINGLETON_ID,
        "default_chat_provider_id": 1,
    }
    defaults.update(overrides)
    return LlmGlobalSetting(**defaults)  # type: ignore[arg-type]


class TestGetSingleton:
    async def test_returns_when_found(self, repo: LlmGlobalSettingRepository, session: AsyncMock) -> None:
        setting = _make_setting()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = setting
        session.execute.return_value = mock_result
        assert await repo.get_singleton(session) is setting

    async def test_returns_none_when_missing(self, repo: LlmGlobalSettingRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result
        assert await repo.get_singleton(session) is None


class TestSave:
    async def test_adds_and_flushes(self, repo: LlmGlobalSettingRepository, session: AsyncMock) -> None:
        setting = _make_setting()
        result = await repo.save(session, setting)
        session.add.assert_called_once_with(setting)
        session.flush.assert_awaited_once()
        assert result is setting
