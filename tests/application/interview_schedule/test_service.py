from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.interview_schedule.schemas import CreateScheduleRequest
from app.application.interview_schedule.service import ScheduleService
from app.domain.entities.interview_schedule import InterviewStatus
from app.domain.errors import BusinessException, ErrorCode
from app.infrastructure.db.models.interview_schedule import InterviewSchedule
from app.infrastructure.db.repositories.interview_schedule_repository import InterviewScheduleRepository


def _make_schedule(
    schedule_id: int = 1,
    company_name: str = "阿里巴巴",
    position: str = "Java工程师",
    status: str = InterviewStatus.PENDING.value,
) -> InterviewSchedule:
    return InterviewSchedule(
        id=schedule_id,
        company_name=company_name,
        position=position,
        interview_time=datetime(2026, 8, 1, 14, 0, 0),
        interview_type="VIDEO",
        meeting_link="https://meeting.feishu.cn/xxx",
        round_number=1,
        interviewer="张三",
        notes="技术面",
        status=status,
        created_at=datetime(2026, 7, 21, 10, 0, 0),
        updated_at=datetime(2026, 7, 21, 10, 0, 0),
    )


def _make_request(
    company_name: str = "阿里巴巴",
    position: str = "Java工程师",
) -> CreateScheduleRequest:
    return CreateScheduleRequest(
        company_name=company_name,
        position=position,
        interview_time=datetime(2026, 8, 1, 14, 0, 0),
        interview_type="VIDEO",
        meeting_link="https://meeting.feishu.cn/xxx",
        round_number=1,
        interviewer="张三",
        notes="技术面",
    )


@pytest.fixture()
def mock_repository() -> MagicMock:
    repo = MagicMock(spec=InterviewScheduleRepository)
    repo.save = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.list_all = AsyncMock()
    repo.list_by_status = AsyncMock()
    repo.list_by_time_range = AsyncMock()
    repo.delete = AsyncMock()
    repo.cancel_expired = AsyncMock()
    return repo


@pytest.fixture()
def mock_session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture()
def service(mock_repository: MagicMock, mock_session: MagicMock) -> ScheduleService:
    return ScheduleService(session=mock_session, repository=mock_repository)


class TestCreateSchedule:
    async def test_create_returns_dto_with_pending_status(
        self, service: ScheduleService, mock_repository: MagicMock
    ) -> None:
        def _save_side_effect(session, schedule):
            schedule.id = 1
            return schedule

        mock_repository.save.side_effect = _save_side_effect

        dto = await service.create(_make_request())

        assert dto.id == 1
        assert dto.company_name == "阿里巴巴"
        assert dto.position == "Java工程师"
        assert dto.status == InterviewStatus.PENDING.value
        assert dto.round_number == 1
        saved = mock_repository.save.call_args[0][1]
        assert saved.status == InterviewStatus.PENDING.value


class TestGetById:
    async def test_get_by_id_returns_dto(self, service: ScheduleService, mock_repository: MagicMock) -> None:
        mock_repository.get_by_id.return_value = _make_schedule(schedule_id=42)

        dto = await service.get_by_id(42)

        assert dto.id == 42
        assert dto.company_name == "阿里巴巴"

    async def test_get_by_id_not_found_raises(self, service: ScheduleService, mock_repository: MagicMock) -> None:
        mock_repository.get_by_id.return_value = None

        with pytest.raises(BusinessException) as exc_info:
            await service.get_by_id(999)

        assert exc_info.value.error_code == ErrorCode.INTERVIEW_SCHEDULE_NOT_FOUND


class TestListSchedules:
    async def test_list_all_no_filter(self, service: ScheduleService, mock_repository: MagicMock) -> None:
        mock_repository.list_all.return_value = [_make_schedule(1), _make_schedule(2)]

        dtos = await service.list_schedules(status=None, start=None, end=None)

        assert len(dtos) == 2
        mock_repository.list_all.assert_called_once()

    async def test_list_by_status(self, service: ScheduleService, mock_repository: MagicMock) -> None:
        mock_repository.list_by_status.return_value = [_make_schedule(1, status=InterviewStatus.PENDING.value)]

        dtos = await service.list_schedules(status="PENDING", start=None, end=None)

        assert len(dtos) == 1
        mock_repository.list_by_status.assert_called_once()

    async def test_list_by_time_range(self, service: ScheduleService, mock_repository: MagicMock) -> None:
        start = datetime(2026, 8, 1)
        end = datetime(2026, 8, 31)
        mock_repository.list_by_time_range.return_value = [_make_schedule(1)]

        dtos = await service.list_schedules(status=None, start=start, end=end)

        assert len(dtos) == 1
        mock_repository.list_by_time_range.assert_called_once()


class TestUpdateSchedule:
    async def test_update_success(self, service: ScheduleService, mock_repository: MagicMock) -> None:
        existing = _make_schedule(schedule_id=1)
        mock_repository.get_by_id.return_value = existing

        dto = await service.update(1, _make_request(company_name="腾讯", position="Python工程师"))

        assert dto.company_name == "腾讯"
        assert dto.position == "Python工程师"
        assert existing.company_name == "腾讯"
        assert existing.position == "Python工程师"

    async def test_update_not_found_raises(self, service: ScheduleService, mock_repository: MagicMock) -> None:
        mock_repository.get_by_id.return_value = None

        with pytest.raises(BusinessException) as exc_info:
            await service.update(999, _make_request())

        assert exc_info.value.error_code == ErrorCode.INTERVIEW_SCHEDULE_NOT_FOUND


class TestDeleteSchedule:
    async def test_delete_success(self, service: ScheduleService, mock_repository: MagicMock) -> None:
        existing = _make_schedule(schedule_id=1)
        mock_repository.get_by_id.return_value = existing

        await service.delete(1)

        mock_repository.delete.assert_called_once()

    async def test_delete_not_found_raises(self, service: ScheduleService, mock_repository: MagicMock) -> None:
        mock_repository.get_by_id.return_value = None

        with pytest.raises(BusinessException) as exc_info:
            await service.delete(999)

        assert exc_info.value.error_code == ErrorCode.INTERVIEW_SCHEDULE_NOT_FOUND


class TestUpdateStatus:
    async def test_update_status_success(self, service: ScheduleService, mock_repository: MagicMock) -> None:
        existing = _make_schedule(schedule_id=1, status=InterviewStatus.PENDING.value)
        mock_repository.get_by_id.return_value = existing

        dto = await service.update_status(1, InterviewStatus.COMPLETED)

        assert dto.status == InterviewStatus.COMPLETED.value
        assert existing.status == InterviewStatus.COMPLETED.value

    async def test_update_status_not_found_raises(self, service: ScheduleService, mock_repository: MagicMock) -> None:
        mock_repository.get_by_id.return_value = None

        with pytest.raises(BusinessException) as exc_info:
            await service.update_status(999, InterviewStatus.COMPLETED)

        assert exc_info.value.error_code == ErrorCode.INTERVIEW_SCHEDULE_NOT_FOUND
