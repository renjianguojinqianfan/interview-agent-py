from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.entities.voice_interview import (
    EVAL_PROCESSING_TIMEOUT_SECONDS,
    PAUSE_IDLE_TIMEOUT_SECONDS,
    ZOMBIE_SESSION_TIMEOUT_SECONDS,
)
from app.infrastructure.scheduler import jobs

_NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC)


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # noqa: ANN401
        return _NOW


class _SessionCtx:
    def __init__(self, session: MagicMock) -> None:
        self._session = session

    async def __aenter__(self) -> MagicMock:
        return self._session

    async def __aexit__(self, *args: object) -> bool:
        return False


@pytest.fixture()
def session() -> MagicMock:
    mock = MagicMock()
    mock.commit = AsyncMock()
    return mock


@pytest.fixture()
def session_factory(session: MagicMock) -> MagicMock:
    factory = MagicMock()
    factory.return_value = _SessionCtx(session)
    return factory


@pytest.fixture(autouse=True)
def _freeze_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "datetime", _FixedDateTime)


class TestCancelExpiredSchedules:
    async def test_calls_cancel_expired_with_now_and_commits(
        self, monkeypatch: pytest.MonkeyPatch, session_factory: MagicMock, session: MagicMock
    ) -> None:
        repo = MagicMock()
        repo.cancel_expired = AsyncMock(return_value=2)
        monkeypatch.setattr(jobs, "InterviewScheduleRepository", MagicMock(return_value=repo))

        await jobs.cancel_expired_schedules(session_factory)

        repo.cancel_expired.assert_awaited_once_with(session, _NOW)
        session.commit.assert_awaited_once()


class TestPauseIdleVoiceSessions:
    async def test_uses_five_minute_threshold(
        self, monkeypatch: pytest.MonkeyPatch, session_factory: MagicMock, session: MagicMock
    ) -> None:
        repo = MagicMock()
        repo.bulk_pause_idle_in_progress = AsyncMock(return_value=1)
        monkeypatch.setattr(jobs, "VoiceInterviewRepository", MagicMock(return_value=repo))

        await jobs.pause_idle_voice_sessions(session_factory)

        expected = _NOW - timedelta(seconds=PAUSE_IDLE_TIMEOUT_SECONDS)
        repo.bulk_pause_idle_in_progress.assert_awaited_once_with(session, expected)
        session.commit.assert_awaited_once()


class TestCleanupVoiceZombieSessions:
    async def test_completes_zombies_and_fails_stuck_evaluations(
        self, monkeypatch: pytest.MonkeyPatch, session_factory: MagicMock, session: MagicMock
    ) -> None:
        repo = MagicMock()
        repo.bulk_complete_zombie_sessions = AsyncMock(return_value=1)
        repo.bulk_fail_stuck_evaluations = AsyncMock(return_value=2)
        monkeypatch.setattr(jobs, "VoiceInterviewRepository", MagicMock(return_value=repo))

        await jobs.cleanup_voice_zombie_sessions(session_factory)

        repo.bulk_complete_zombie_sessions.assert_awaited_once_with(
            session, _NOW - timedelta(seconds=ZOMBIE_SESSION_TIMEOUT_SECONDS)
        )
        repo.bulk_fail_stuck_evaluations.assert_awaited_once_with(
            session, _NOW - timedelta(seconds=EVAL_PROCESSING_TIMEOUT_SECONDS)
        )
        session.commit.assert_awaited_once()
