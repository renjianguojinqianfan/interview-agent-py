from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.db.models.rag_chat import RagChatMessage, RagChatSession
from app.infrastructure.db.repositories.rag_chat_repository import RagChatRepository


@pytest.fixture()
def session() -> MagicMock:
    mock = MagicMock()
    mock.execute = AsyncMock()
    mock.flush = AsyncMock()
    mock.delete = AsyncMock()
    return mock


@pytest.fixture()
def repo() -> RagChatRepository:
    return RagChatRepository()


def _make_session(**overrides: object) -> RagChatSession:
    defaults: dict[str, object] = {
        "id": 1,
        "session_id": "uuid-1",
        "knowledge_base_ids_json": "[1,2]",
    }
    defaults.update(overrides)
    return RagChatSession(**defaults)  # type: ignore[arg-type]


def _make_message(**overrides: object) -> RagChatMessage:
    defaults: dict[str, object] = {
        "id": 1,
        "session_id": 1,
        "role": "user",
        "content": "hi",
    }
    defaults.update(overrides)
    return RagChatMessage(**defaults)  # type: ignore[arg-type]


class TestGetById:
    async def test_found(self, repo: RagChatRepository, session: AsyncMock) -> None:
        entity = _make_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = entity
        session.execute.return_value = mock_result
        assert await repo.get_by_id(session, 1) is entity

    async def test_none(self, repo: RagChatRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result
        assert await repo.get_by_id(session, 999) is None


class TestSave:
    async def test_adds_and_flushes(self, repo: RagChatRepository, session: AsyncMock) -> None:
        entity = _make_session()
        result = await repo.save(session, entity)
        session.add.assert_called_once_with(entity)
        session.flush.assert_awaited_once()
        assert result is entity


class TestListAll:
    async def test_returns_all(self, repo: RagChatRepository, session: AsyncMock) -> None:
        sessions = [_make_session(id=1), _make_session(id=2, session_id="uuid-2")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = sessions
        session.execute.return_value = mock_result
        assert await repo.list_all(session) == sessions


class TestDelete:
    async def test_deletes(self, repo: RagChatRepository, session: AsyncMock) -> None:
        entity = _make_session()
        await repo.delete(session, entity)
        session.delete.assert_awaited_once_with(entity)


class TestUpdatePinned:
    async def test_updates_pinned(self, repo: RagChatRepository, session: AsyncMock) -> None:
        entity = _make_session(pinned=False)
        await repo.update_pinned(session, entity, True)
        assert entity.pinned is True
        session.flush.assert_awaited_once()


class TestUpdateTitle:
    async def test_updates_title(self, repo: RagChatRepository, session: AsyncMock) -> None:
        entity = _make_session()
        await repo.update_title(session, entity, "新标题")
        assert entity.title == "新标题"
        session.flush.assert_awaited_once()


class TestCountMessages:
    async def test_returns_count(self, repo: RagChatRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        session.execute.return_value = mock_result
        assert await repo.count_messages(session, 1) == 5

    async def test_defaults_zero(self, repo: RagChatRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        session.execute.return_value = mock_result
        assert await repo.count_messages(session, 1) == 0


class TestAddMessage:
    async def test_adds_and_flushes(self, repo: RagChatRepository, session: AsyncMock) -> None:
        message = _make_message()
        result = await repo.add_message(session, message)
        session.add.assert_called_once_with(message)
        session.flush.assert_awaited_once()
        assert result is message


class TestCountMessagesByRole:
    async def test_returns_count(self, repo: RagChatRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        session.execute.return_value = mock_result
        assert await repo.count_messages_by_role(session, "assistant") == 3


class TestListMessages:
    async def test_returns_ordered(self, repo: RagChatRepository, session: AsyncMock) -> None:
        messages = [_make_message(id=1), _make_message(id=2)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = messages
        session.execute.return_value = mock_result
        assert await repo.list_messages(session, 1) == messages


class TestRecentHistory:
    async def test_reverses_desc_result_to_chronological(self, repo: RagChatRepository, session: AsyncMock) -> None:
        # DB 按时间倒序返回，仓储需 reverse 成正序
        newest, middle, oldest = _make_message(id=3), _make_message(id=2), _make_message(id=1)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [newest, middle, oldest]
        session.execute.return_value = mock_result
        result = await repo.recent_history(session, 1, 3)
        assert result == [oldest, middle, newest]
