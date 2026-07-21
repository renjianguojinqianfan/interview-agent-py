from unittest.mock import AsyncMock, MagicMock, patch

from app.infrastructure.scheduler.jobs import (
    cancel_expired_schedules,
    cleanup_voice_zombie_sessions,
    pause_idle_voice_sessions,
)
from app.infrastructure.scheduler.manager import SchedulerManager


class TestSchedulerManager:
    def test_register_job_adds_to_scheduler(self) -> None:
        manager = SchedulerManager()

        async def dummy_job() -> None:
            pass

        manager.register_job(dummy_job, "cron", hour="*", minute=0, id="test_job")

        jobs = manager.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == "test_job"

    def test_start_calls_scheduler_start(self) -> None:
        manager = SchedulerManager()
        with patch.object(manager._scheduler, "start") as mock_start:
            manager.start()
            mock_start.assert_called_once()

    def test_shutdown_calls_scheduler_shutdown(self) -> None:
        manager = SchedulerManager()
        with patch.object(manager._scheduler, "shutdown") as mock_shutdown:
            manager.shutdown()
            mock_shutdown.assert_called_once_with(wait=True)


class TestCancelExpiredSchedules:
    async def test_cancel_expired_calls_repository_and_commits(self) -> None:
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session

        with patch("app.infrastructure.scheduler.jobs.InterviewScheduleRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.cancel_expired = AsyncMock(return_value=3)
            mock_repo_class.return_value = mock_repo

            await cancel_expired_schedules(mock_factory)

            mock_repo.cancel_expired.assert_called_once()
            mock_session.commit.assert_called_once()

    async def test_cancel_expired_zero_does_not_log_warning(self) -> None:
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session

        with patch("app.infrastructure.scheduler.jobs.InterviewScheduleRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.cancel_expired = AsyncMock(return_value=0)
            mock_repo_class.return_value = mock_repo

            await cancel_expired_schedules(mock_factory)

            mock_session.commit.assert_called_once()


def _mock_session_factory() -> tuple[MagicMock, MagicMock]:
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory = MagicMock()
    mock_factory.return_value = mock_session
    return mock_factory, mock_session


class TestPauseIdleVoiceSessions:
    async def test_pauses_idle_sessions_and_commits(self) -> None:
        mock_factory, mock_session = _mock_session_factory()
        with patch("app.infrastructure.scheduler.jobs.VoiceInterviewRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.bulk_pause_idle_in_progress = AsyncMock(return_value=2)
            mock_repo_class.return_value = mock_repo

            await pause_idle_voice_sessions(mock_factory)

            mock_repo.bulk_pause_idle_in_progress.assert_called_once()
            mock_session.commit.assert_called_once()

    async def test_zero_count_still_commits(self) -> None:
        mock_factory, mock_session = _mock_session_factory()
        with patch("app.infrastructure.scheduler.jobs.VoiceInterviewRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.bulk_pause_idle_in_progress = AsyncMock(return_value=0)
            mock_repo_class.return_value = mock_repo

            await pause_idle_voice_sessions(mock_factory)

            mock_session.commit.assert_called_once()

    async def test_threshold_is_five_minutes_before_now(self) -> None:
        """验证阈值 = now - 5min（PAUSE_IDLE_TIMEOUT_SECONDS=300）。"""
        from datetime import datetime

        mock_factory, _ = _mock_session_factory()
        captured: dict[str, object] = {}

        async def fake_bulk(session: object, threshold: datetime) -> int:
            captured["threshold"] = threshold
            return 0

        with patch("app.infrastructure.scheduler.jobs.VoiceInterviewRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.bulk_pause_idle_in_progress = fake_bulk
            mock_repo_class.return_value = mock_repo

            before = datetime.now()
            await pause_idle_voice_sessions(mock_factory)

        threshold = captured["threshold"]
        assert isinstance(threshold, datetime)
        # 阈值 = now - 300s，允许微小时间漂移
        delta = (before - threshold).total_seconds()
        assert 299.0 <= delta <= 301.0


class TestCleanupVoiceZombieSessions:
    async def test_completes_zombies_and_fails_stuck_evals(self) -> None:
        mock_factory, mock_session = _mock_session_factory()
        with patch("app.infrastructure.scheduler.jobs.VoiceInterviewRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.bulk_complete_zombie_sessions = AsyncMock(return_value=1)
            mock_repo.bulk_fail_stuck_evaluations = AsyncMock(return_value=1)
            mock_repo_class.return_value = mock_repo

            await cleanup_voice_zombie_sessions(mock_factory)

            mock_repo.bulk_complete_zombie_sessions.assert_called_once()
            mock_repo.bulk_fail_stuck_evaluations.assert_called_once()
            mock_session.commit.assert_called_once()

    async def test_zero_counts_still_commits(self) -> None:
        mock_factory, mock_session = _mock_session_factory()
        with patch("app.infrastructure.scheduler.jobs.VoiceInterviewRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.bulk_complete_zombie_sessions = AsyncMock(return_value=0)
            mock_repo.bulk_fail_stuck_evaluations = AsyncMock(return_value=0)
            mock_repo_class.return_value = mock_repo

            await cleanup_voice_zombie_sessions(mock_factory)

            mock_session.commit.assert_called_once()
