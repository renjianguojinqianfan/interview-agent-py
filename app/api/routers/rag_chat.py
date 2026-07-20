from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_rag_chat_service
from app.api.rate_limit import global_key, limiter
from app.api.responses import Result
from app.application.rag.schemas import (
    CreateRagSessionRequest,
    RagAnswerDTO,
    RagMessageDTO,
    RagQueryRequest,
    RagSessionDetailDTO,
    RagSessionInfoDTO,
    RagSessionPageDTO,
)
from app.application.rag.service import RagChatService

router = APIRouter(prefix="/api/rag/sessions", tags=["RAG 问答"])


@router.post("", response_model=Result[RagSessionInfoDTO])
async def create_session(
    body: CreateRagSessionRequest,
    service: RagChatService = Depends(get_rag_chat_service),
) -> Result[RagSessionInfoDTO]:
    data = await service.create_session(body.knowledge_base_ids, body.title)
    return Result.success(data=data)


@router.get("", response_model=Result[RagSessionPageDTO])
async def list_sessions(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    service: RagChatService = Depends(get_rag_chat_service),
) -> Result[RagSessionPageDTO]:
    data = await service.list_sessions(page=page, size=size)
    return Result.success(data=data)


@router.get("/{session_id}", response_model=Result[RagSessionDetailDTO])
async def get_session(
    session_id: str,
    service: RagChatService = Depends(get_rag_chat_service),
) -> Result[RagSessionDetailDTO]:
    data = await service.get_detail(session_id)
    return Result.success(data=data)


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    service: RagChatService = Depends(get_rag_chat_service),
) -> Result[None]:
    await service.delete(session_id)
    return Result.success(data=None)


@router.post("/{session_id}/pin", response_model=Result[bool])
async def pin_session(
    session_id: str,
    service: RagChatService = Depends(get_rag_chat_service),
) -> Result[bool]:
    pinned = await service.toggle_pin(session_id)
    return Result.success(data=pinned)


@router.get("/{session_id}/messages", response_model=Result[list[RagMessageDTO]])
async def list_messages(
    session_id: str,
    service: RagChatService = Depends(get_rag_chat_service),
) -> Result[list[RagMessageDTO]]:
    data = await service.get_messages(session_id)
    return Result.success(data=data)


@router.post("/{session_id}/query", response_model=Result[RagAnswerDTO])
@limiter.limit("10/second", key_func=global_key)
@limiter.limit("10/second")
async def query(
    request: Request,  # noqa: ARG001  slowapi 限流必需
    session_id: str,
    body: RagQueryRequest,
    service: RagChatService = Depends(get_rag_chat_service),
) -> Result[RagAnswerDTO]:
    data = await service.query(session_id, body.question)
    return Result.success(data=data)


@router.post("/{session_id}/query/stream")
@limiter.limit("5/second", key_func=global_key)
@limiter.limit("5/second")
async def query_stream(
    request: Request,  # noqa: ARG001  slowapi 限流必需
    session_id: str,
    body: RagQueryRequest,
    service: RagChatService = Depends(get_rag_chat_service),
) -> StreamingResponse:
    await service.ensure_session_exists(session_id)
    return StreamingResponse(
        service.stream_query(session_id, body.question),
        media_type="text/event-stream",
    )
