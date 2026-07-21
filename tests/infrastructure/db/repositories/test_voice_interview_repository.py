"""VoiceInterviewRepository #17 新增方法测试：阶段更新 + 未作答消息回填查询。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.db.models.voice_interview import (
    VoiceInterviewSession as VoiceInterviewSessionORM,
)
from app.infrastructure.db.repositories.voice_interview_repository import VoiceInterviewRepository


@pytest.fixture()
def session() -> MagicMock:
    mock = MagicMock()
    mock.execute = AsyncMock()
    mock.flush = AsyncMock()
    return mock


@pytest.fixture()
def repo() -> VoiceInterviewRepository:
    return VoiceInterviewRepository()


class TestUpdateCurrentPhase:
    async def test_mutates_and_flushes(self, repo: VoiceInterviewRepository, session: AsyncMock) -> None:
        orm = VoiceInterviewSessionORM(current_phase="INTRO")
        await repo.update_current_phase(session, orm, "TECH")
        assert orm.current_phase == "TECH"
        session.flush.assert_awaited_once()


class TestFindLatestUnansweredMessage:
    async def test_returns_scalar_result(self, repo: VoiceInterviewRepository, session: AsyncMock) -> None:
        expected = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = expected
        session.execute.return_value = result_mock

        found = await repo.find_latest_unanswered_message(session, 1)

        assert found is expected
        session.execute.assert_awaited_once()

    async def test_returns_none_when_absent(self, repo: VoiceInterviewRepository, session: AsyncMock) -> None:
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock

        assert await repo.find_latest_unanswered_message(session, 1) is None
