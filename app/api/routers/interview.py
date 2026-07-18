"""文字面试 API 路由：会话创建、问答交互、提前交卷、断线续答。"""

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_interview_session_service
from app.api.rate_limit import global_key, limiter
from app.api.responses import Result
from app.application.interview.schemas import (
    CreateSessionRequest,
    CurrentQuestionResponse,
    InterviewSessionDTO,
    SessionPageDTO,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
)
from app.application.interview.session_service import InterviewSessionService

router = APIRouter(prefix="/api/interview", tags=["模拟面试"])


@router.post("/sessions", response_model=Result[InterviewSessionDTO])
@limiter.limit("5/second", key_func=global_key)
@limiter.limit("5/second")
async def create_session(
    request: Request,  # noqa: ARG001  slowapi 限流必需
    body: CreateSessionRequest,
    service: InterviewSessionService = Depends(get_interview_session_service),
) -> Result[InterviewSessionDTO]:
    data = await service.create_session(body)
    return Result.success(data=data)


@router.get("/sessions", response_model=Result[SessionPageDTO])
async def list_sessions(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    service: InterviewSessionService = Depends(get_interview_session_service),
) -> Result[SessionPageDTO]:
    data = await service.list_sessions(page=page, size=size)
    return Result.success(data=data)


@router.get("/sessions/unfinished/{resume_id}", response_model=Result[InterviewSessionDTO])
async def find_unfinished_session(
    resume_id: int,
    service: InterviewSessionService = Depends(get_interview_session_service),
) -> Result[InterviewSessionDTO]:
    data = await service.find_unfinished_session(resume_id)
    return Result.success(data=data)


@router.get("/sessions/{session_id}", response_model=Result[InterviewSessionDTO])
async def get_session(
    session_id: str,
    service: InterviewSessionService = Depends(get_interview_session_service),
) -> Result[InterviewSessionDTO]:
    data = await service.get_session(session_id)
    return Result.success(data=data)


@router.get("/sessions/{session_id}/question", response_model=Result[CurrentQuestionResponse])
async def get_current_question(
    session_id: str,
    service: InterviewSessionService = Depends(get_interview_session_service),
) -> Result[CurrentQuestionResponse]:
    data = await service.get_current_question(session_id)
    return Result.success(data=data)


@router.post("/sessions/{session_id}/answers", response_model=Result[SubmitAnswerResponse])
@limiter.limit("10/second", key_func=global_key)
async def submit_answer(
    request: Request,  # noqa: ARG001  slowapi 限流必需
    session_id: str,
    body: SubmitAnswerRequest,
    service: InterviewSessionService = Depends(get_interview_session_service),
) -> Result[SubmitAnswerResponse]:
    data = await service.submit_answer(session_id, body)
    return Result.success(data=data)


@router.put("/sessions/{session_id}/answers", response_model=Result[None])
async def save_answer(
    session_id: str,
    body: SubmitAnswerRequest,
    service: InterviewSessionService = Depends(get_interview_session_service),
) -> Result[None]:
    await service.save_answer(session_id, body)
    return Result.success(data=None)


@router.post("/sessions/{session_id}/complete", response_model=Result[None])
async def complete_interview(
    session_id: str,
    service: InterviewSessionService = Depends(get_interview_session_service),
) -> Result[None]:
    await service.complete_interview(session_id)
    return Result.success(data=None)


@router.delete("/sessions/{session_id}", response_model=Result[None])
async def delete_session(
    session_id: str,
    service: InterviewSessionService = Depends(get_interview_session_service),
) -> Result[None]:
    await service.delete_session(session_id)
    return Result.success(data=None)
