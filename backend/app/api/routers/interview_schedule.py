from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_schedule_parse_service, get_schedule_service
from app.api.rate_limit import limiter
from app.api.responses import Result
from app.application.interview_schedule.schemas import (
    CreateScheduleRequest,
    InterviewScheduleDTO,
    ParseRequest,
    ParseResponse,
)
from app.application.interview_schedule.service import ScheduleParseService, ScheduleService
from app.domain.entities.interview_schedule import InterviewStatus

router = APIRouter(prefix="/api/interview-schedule", tags=["面试日程管理"])


@router.post("/parse", response_model=Result[ParseResponse])
@limiter.limit("5/second")
async def parse_schedule(
    request: Request,  # noqa: ARG001
    body: ParseRequest,
    service: ScheduleParseService = Depends(get_schedule_parse_service),
) -> Result[ParseResponse]:
    return Result.success(data=await service.parse(body.raw_text, body.source))


@router.post("", response_model=Result[InterviewScheduleDTO])
async def create_schedule(
    body: CreateScheduleRequest,
    service: ScheduleService = Depends(get_schedule_service),
) -> Result[InterviewScheduleDTO]:
    return Result.success(data=await service.create(body))


@router.get("", response_model=Result[list[InterviewScheduleDTO]])
async def list_schedules(
    status: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    service: ScheduleService = Depends(get_schedule_service),
) -> Result[list[InterviewScheduleDTO]]:
    return Result.success(data=await service.list_schedules(status=status, start=start, end=end))


@router.get("/{schedule_id}", response_model=Result[InterviewScheduleDTO])
async def get_schedule(
    schedule_id: int,
    service: ScheduleService = Depends(get_schedule_service),
) -> Result[InterviewScheduleDTO]:
    return Result.success(data=await service.get_by_id(schedule_id))


@router.put("/{schedule_id}", response_model=Result[InterviewScheduleDTO])
async def update_schedule(
    schedule_id: int,
    body: CreateScheduleRequest,
    service: ScheduleService = Depends(get_schedule_service),
) -> Result[InterviewScheduleDTO]:
    return Result.success(data=await service.update(schedule_id, body))


@router.delete("/{schedule_id}", response_model=Result[None])
async def delete_schedule(
    schedule_id: int,
    service: ScheduleService = Depends(get_schedule_service),
) -> Result[None]:
    await service.delete(schedule_id)
    return Result.success()


@router.patch("/{schedule_id}/status", response_model=Result[InterviewScheduleDTO])
async def update_schedule_status(
    schedule_id: int,
    status: InterviewStatus = Query(...),
    service: ScheduleService = Depends(get_schedule_service),
) -> Result[InterviewScheduleDTO]:
    return Result.success(data=await service.update_status(schedule_id, status))
