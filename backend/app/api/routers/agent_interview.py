"""自适应面试 Agent API 路由：独立于现有面试 API，展示 ReAct Agent 循环。"""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_agent_interview_service
from app.api.responses import Result
from app.application.agent.adaptive_service import AdaptiveInterviewService
from app.application.agent.schemas import (
    AdaptiveAnswerResultDTO,
    AdaptiveReportDTO,
    AdaptiveSessionDTO,
    CreateAdaptiveSessionRequest,
    SubmitAdaptiveAnswerRequest,
)

router = APIRouter(prefix="/api/agent/interview", tags=["自适应面试Agent"])


@router.post("/sessions", response_model=Result[AdaptiveSessionDTO])
async def create_adaptive_session(
    body: CreateAdaptiveSessionRequest,
    service: AdaptiveInterviewService = Depends(get_agent_interview_service),
) -> Result[AdaptiveSessionDTO]:
    """创建自适应面试会话。Agent 自动生成第一题。"""
    data = await service.create_session(body)
    return Result.success(data=data)


@router.get("/sessions/{session_id}", response_model=Result[AdaptiveSessionDTO])
async def get_adaptive_session(
    session_id: str,
    service: AdaptiveInterviewService = Depends(get_agent_interview_service),
) -> Result[AdaptiveSessionDTO]:
    """获取自适应面试会话当前状态。"""
    data = await service.get_session(session_id)
    return Result.success(data=data)


@router.post("/sessions/{session_id}/answer", response_model=Result[AdaptiveAnswerResultDTO])
async def submit_adaptive_answer(
    session_id: str,
    body: SubmitAdaptiveAnswerRequest,
    service: AdaptiveInterviewService = Depends(get_agent_interview_service),
) -> Result[AdaptiveAnswerResultDTO]:
    """提交答案。Agent 自动评估并决定下一步（出题/追问/调难度/结束）。"""
    data = await service.submit_answer(session_id, body.answer)
    return Result.success(data=data)


@router.post("/sessions/{session_id}/answer/stream")
async def submit_adaptive_answer_stream(
    session_id: str,
    body: SubmitAdaptiveAnswerRequest,
    service: AdaptiveInterviewService = Depends(get_agent_interview_service),
) -> StreamingResponse:
    """流式提交答案。Agent 思考过程以 SSE 事件流推送给前端。"""

    async def event_stream() -> AsyncIterator[str]:
        async for event in service.stream_answer(session_id, body.answer):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/sessions/{session_id}/result", response_model=Result[AdaptiveReportDTO])
async def get_adaptive_result(
    session_id: str,
    service: AdaptiveInterviewService = Depends(get_agent_interview_service),
) -> Result[AdaptiveReportDTO]:
    """获取面试结果报告。"""
    data = await service.get_report(session_id)
    return Result.success(data=data)
