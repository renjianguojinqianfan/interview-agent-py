from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_schedule_parse_service, get_schedule_service
from app.application.interview_schedule.schemas import (
    CreateScheduleRequest,
    InterviewScheduleDTO,
    ParseResponse,
)
from app.domain.entities.interview_schedule import InterviewStatus
from app.main import app

client = TestClient(app)


def _schedule_dto(
    schedule_id: int = 1,
    status: str = InterviewStatus.PENDING.value,
) -> InterviewScheduleDTO:
    return InterviewScheduleDTO(
        id=schedule_id,
        company_name="阿里巴巴",
        position="Java工程师",
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


def _create_request() -> dict:
    return {
        "companyName": "阿里巴巴",
        "position": "Java工程师",
        "interviewTime": "2026-08-01T14:00:00",
        "interviewType": "VIDEO",
        "meetingLink": "https://meeting.feishu.cn/xxx",
        "roundNumber": 1,
        "interviewer": "张三",
        "notes": "技术面",
    }


def _override_services(mock_schedule: AsyncMock, mock_parse: AsyncMock) -> None:
    app.dependency_overrides[get_schedule_service] = lambda: mock_schedule
    app.dependency_overrides[get_schedule_parse_service] = lambda: mock_parse


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


class TestParseSchedule:
    def test_parse_success(self) -> None:
        mock_schedule = AsyncMock()
        mock_parse = AsyncMock()
        mock_parse.parse.return_value = ParseResponse(
            success=True,
            data=CreateScheduleRequest(
                company_name="阿里巴巴",
                position="Java工程师",
                interview_time=datetime(2026, 8, 1, 14, 0, 0),
                interview_type="VIDEO",
            ),
            confidence=0.95,
            parse_method="rule",
            log="规则解析成功",
        )
        _override_services(mock_schedule, mock_parse)

        resp = client.post("/api/interview-schedule/parse", json={"rawText": "飞书邀约文本", "source": "feishu"})

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["success"] is True
        assert data["parseMethod"] == "rule"
        assert data["data"]["companyName"] == "阿里巴巴"


class TestCreateSchedule:
    def test_create_success(self) -> None:
        mock_schedule = AsyncMock()
        mock_schedule.create.return_value = _schedule_dto(schedule_id=10)
        mock_parse = AsyncMock()
        _override_services(mock_schedule, mock_parse)

        resp = client.post("/api/interview-schedule", json=_create_request())

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["id"] == 10
        assert data["status"] == "PENDING"


class TestGetSchedule:
    def test_get_by_id_success(self) -> None:
        mock_schedule = AsyncMock()
        mock_schedule.get_by_id.return_value = _schedule_dto(schedule_id=42)
        mock_parse = AsyncMock()
        _override_services(mock_schedule, mock_parse)

        resp = client.get("/api/interview-schedule/42")

        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == 42


class TestListSchedules:
    def test_list_no_filter(self) -> None:
        mock_schedule = AsyncMock()
        mock_schedule.list_schedules.return_value = [_schedule_dto(1), _schedule_dto(2)]
        mock_parse = AsyncMock()
        _override_services(mock_schedule, mock_parse)

        resp = client.get("/api/interview-schedule")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2

    def test_list_with_status_filter(self) -> None:
        mock_schedule = AsyncMock()
        mock_schedule.list_schedules.return_value = [_schedule_dto(1, status="COMPLETED")]
        mock_parse = AsyncMock()
        _override_services(mock_schedule, mock_parse)

        resp = client.get("/api/interview-schedule?status=COMPLETED")

        assert resp.status_code == 200
        mock_schedule.list_schedules.assert_called_once_with(status="COMPLETED", start=None, end=None)


class TestUpdateSchedule:
    def test_update_success(self) -> None:
        mock_schedule = AsyncMock()
        mock_schedule.update.return_value = _schedule_dto(schedule_id=1)
        mock_parse = AsyncMock()
        _override_services(mock_schedule, mock_parse)

        resp = client.put("/api/interview-schedule/1", json=_create_request())

        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == 1


class TestDeleteSchedule:
    def test_delete_success(self) -> None:
        mock_schedule = AsyncMock()
        mock_schedule.delete.return_value = None
        mock_parse = AsyncMock()
        _override_services(mock_schedule, mock_parse)

        resp = client.delete("/api/interview-schedule/1")

        assert resp.status_code == 200


class TestUpdateStatus:
    def test_update_status_success(self) -> None:
        mock_schedule = AsyncMock()
        mock_schedule.update_status.return_value = _schedule_dto(schedule_id=1, status="COMPLETED")
        mock_parse = AsyncMock()
        _override_services(mock_schedule, mock_parse)

        resp = client.patch("/api/interview-schedule/1/status?status=COMPLETED")

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "COMPLETED"
