from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_voice_evaluation_service, get_voice_session_service
from app.api.rate_limit import limiter
from app.api.responses import Result
from app.application.voice.schemas import (
    CreateVoiceSessionRequest,
    PauseSessionRequest,
    VoiceEvaluationStatusDTO,
    VoiceMessageDTO,
    VoiceSessionDTO,
    VoiceSessionMetaDTO,
)
from app.application.voice.service import VoiceEvaluationService, VoiceSessionService

router = APIRouter(prefix="/api/voice-interview", tags=["语音面试"])


def _attach_ws_url(request: Request, dto: VoiceSessionDTO) -> VoiceSessionDTO:
    """按当前请求的 scheme/host 拼出前端可直接连接的 WebSocket URL。"""
    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host") or request.url.netloc
    dto.web_socket_url = f"{scheme}://{host}/ws/voice-interview/{dto.id}"
    return dto


@router.post("/sessions", response_model=Result[VoiceSessionDTO])
@limiter.limit("5/second")
async def create_session(
    request: Request,
    body: CreateVoiceSessionRequest,
    service: VoiceSessionService = Depends(get_voice_session_service),
) -> Result[VoiceSessionDTO]:
    return Result.success(data=_attach_ws_url(request, await service.create_session(body)))


@router.get("/sessions", response_model=Result[list[VoiceSessionMetaDTO]])
async def list_sessions(
    user_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    service: VoiceSessionService = Depends(get_voice_session_service),
) -> Result[list[VoiceSessionMetaDTO]]:
    return Result.success(data=await service.list_sessions(user_id=user_id, status=status))


@router.get("/sessions/{session_id}", response_model=Result[VoiceSessionDTO])
async def get_session(
    session_id: int,
    request: Request,
    service: VoiceSessionService = Depends(get_voice_session_service),
) -> Result[VoiceSessionDTO]:
    return Result.success(data=_attach_ws_url(request, await service.get_session(session_id)))


@router.post("/sessions/{session_id}/end", response_model=Result[None])
async def end_session(
    session_id: int,
    service: VoiceSessionService = Depends(get_voice_session_service),
) -> Result[None]:
    await service.end_session(session_id)
    return Result.success()


@router.put("/sessions/{session_id}/pause", response_model=Result[None])
async def pause_session(
    session_id: int,
    body: PauseSessionRequest,
    service: VoiceSessionService = Depends(get_voice_session_service),
) -> Result[None]:
    await service.pause_session(session_id, body.reason)
    return Result.success()


@router.put("/sessions/{session_id}/resume", response_model=Result[VoiceSessionDTO])
async def resume_session(
    session_id: int,
    request: Request,
    service: VoiceSessionService = Depends(get_voice_session_service),
) -> Result[VoiceSessionDTO]:
    return Result.success(data=_attach_ws_url(request, await service.resume_session(session_id)))


@router.delete("/sessions/{session_id}", response_model=Result[None])
async def delete_session(
    session_id: int,
    service: VoiceSessionService = Depends(get_voice_session_service),
) -> Result[None]:
    await service.delete_session(session_id)
    return Result.success()


@router.get("/sessions/{session_id}/messages", response_model=Result[list[VoiceMessageDTO]])
async def get_messages(
    session_id: int,
    service: VoiceSessionService = Depends(get_voice_session_service),
) -> Result[list[VoiceMessageDTO]]:
    return Result.success(data=await service.get_messages(session_id))


@router.get("/sessions/{session_id}/evaluation", response_model=Result[VoiceEvaluationStatusDTO])
async def get_evaluation(
    session_id: int,
    service: VoiceEvaluationService = Depends(get_voice_evaluation_service),
) -> Result[VoiceEvaluationStatusDTO]:
    return Result.success(data=await service.get_evaluation(session_id))


@router.post("/sessions/{session_id}/evaluation", response_model=Result[VoiceEvaluationStatusDTO])
async def trigger_evaluation(
    session_id: int,
    service: VoiceSessionService = Depends(get_voice_session_service),
) -> Result[VoiceEvaluationStatusDTO]:
    return Result.success(data=await service.trigger_evaluation(session_id))
