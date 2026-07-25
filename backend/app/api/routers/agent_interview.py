"""自适应面试 Agent API 路由：独立于现有面试 API，展示 ReAct Agent 循环。"""

from fastapi import APIRouter, Depends

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


@router.get("/sessions/{session_id}/result", response_model=Result[AdaptiveReportDTO])
async def get_adaptive_result(
    session_id: str,
    service: AdaptiveInterviewService = Depends(get_agent_interview_service),
) -> Result[AdaptiveReportDTO]:
    """获取面试结果报告。"""
    data = await service.get_report(session_id)
    return Result.success(data=data)
