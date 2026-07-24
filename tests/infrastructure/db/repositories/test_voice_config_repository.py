from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.db.models.voice_config import VoiceConfig
from app.infrastructure.db.repositories.voice_config_repository import VoiceConfigRepository


@pytest.fixture()
def session() -> MagicMock:
    mock = MagicMock()
    mock.execute = AsyncMock()
    mock.flush = AsyncMock()
    return mock


@pytest.fixture()
def repo() -> VoiceConfigRepository:
    return VoiceConfigRepository()


def _make_config(**overrides: object) -> VoiceConfig:
    defaults: dict[str, object] = {"id": VoiceConfig.SINGLETON_ID}
    defaults.update(overrides)
    return VoiceConfig(**defaults)  # type: ignore[arg-type]


class TestGetSingleton:
    async def test_returns_when_found(self, repo: VoiceConfigRepository, session: AsyncMock) -> None:
        config = _make_config()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        session.execute.return_value = mock_result
        assert await repo.get_singleton(session) is config

    async def test_returns_none_when_missing(self, repo: VoiceConfigRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result
        assert await repo.get_singleton(session) is None


class TestSave:
    async def test_adds_and_flushes(self, repo: VoiceConfigRepository, session: AsyncMock) -> None:
        config = _make_config()
        result = await repo.save(session, config)
        session.add.assert_called_once_with(config)
        session.flush.assert_awaited_once()
        assert result is config
