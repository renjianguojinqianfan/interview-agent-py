from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.db.models.interview_schedule import InterviewSchedule
from app.infrastructure.db.repositories.interview_schedule_repository import (
    InterviewScheduleRepository,
)


@pytest.fixture()
def session() -> MagicMock:
    mock = MagicMock()
    mock.execute = AsyncMock()
    mock.flush = AsyncMock()
    mock.delete = AsyncMock()
    return mock


@pytest.fixture()
def repo() -> InterviewScheduleRepository:
    return InterviewScheduleRepository()


def _make_schedule(**overrides: object) -> InterviewSchedule:
    defaults: dict[str, object] = {
        "id": 1,
        "company_name": "Acme",
        "position": "后端工程师",
        "interview_time": datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
        "status": "PENDING",
        "round_number": 1,
    }
    defaults.update(overrides)
    return InterviewSchedule(**defaults)  # type: ignore[arg-type]


class TestSave:
    async def test_adds_and_flushes(self, repo: InterviewScheduleRepository, session: AsyncMock) -> None:
        schedule = _make_schedule()
        result = await repo.save(session, schedule)
        session.add.assert_called_once_with(schedule)
        session.flush.assert_awaited_once()
        assert result is schedule


class TestGetById:
    async def test_returns_when_found(self, repo: InterviewScheduleRepository, session: AsyncMock) -> None:
        schedule = _make_schedule()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = schedule
        session.execute.return_value = mock_result
        assert await repo.get_by_id(session, 1) is schedule

    async def test_returns_none_when_missing(self, repo: InterviewScheduleRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result
        assert await repo.get_by_id(session, 999) is None


class TestListAll:
    async def test_returns_all(self, repo: InterviewScheduleRepository, session: AsyncMock) -> None:
        schedules = [_make_schedule(id=1), _make_schedule(id=2)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = schedules
        session.execute.return_value = mock_result
        assert await repo.list_all(session) == schedules


class TestListByStatus:
    async def test_filters_by_status(self, repo: InterviewScheduleRepository, session: AsyncMock) -> None:
        schedules = [_make_schedule(status="PENDING")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = schedules
        session.execute.return_value = mock_result
        assert await repo.list_by_status(session, "PENDING") == schedules


class TestListByTimeRange:
    async def test_returns_within_range(self, repo: InterviewScheduleRepository, session: AsyncMock) -> None:
        schedules = [_make_schedule()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = schedules
        session.execute.return_value = mock_result
        start = datetime(2026, 7, 1, tzinfo=UTC)
        end = datetime(2026, 7, 31, tzinfo=UTC)
        assert await repo.list_by_time_range(session, start, end) == schedules


class TestDelete:
    async def test_deletes(self, repo: InterviewScheduleRepository, session: AsyncMock) -> None:
        schedule = _make_schedule()
        await repo.delete(session, schedule)
        session.delete.assert_awaited_once_with(schedule)


class TestCancelExpired:
    async def test_returns_rowcount(self, repo: InterviewScheduleRepository, session: AsyncMock) -> None:
        mock_result = MagicMock()
        mock_result.rowcount = 3
        session.execute.return_value = mock_result
        now = datetime(2026, 7, 24, tzinfo=UTC)
        count = await repo.cancel_expired(session, now)
        assert count == 3
        session.execute.assert_awaited_once()

    async def test_defaults_to_zero_without_rowcount(
        self, repo: InterviewScheduleRepository, session: AsyncMock
    ) -> None:
        mock_result = MagicMock(spec=[])  # 结果对象无 rowcount 时兜底为 0
        session.execute.return_value = mock_result
        now = datetime(2026, 7, 24, tzinfo=UTC)
        assert await repo.cancel_expired(session, now) == 0
