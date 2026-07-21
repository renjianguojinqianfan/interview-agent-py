from unittest.mock import AsyncMock, MagicMock, patch

from app.infrastructure.scheduler.jobs import cancel_expired_schedules
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
