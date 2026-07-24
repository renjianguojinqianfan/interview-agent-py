from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_rag_chat_service
from app.api.rate_limit import global_key, limiter
from app.api.responses import Result
from app.application.rag.schemas import (
    CreateRagSessionRequest,
    RagSessionDetailDTO,
    RagSessionDTO,
    RagSessionListItemDTO,
    SendMessageRequest,
    UpdateTitleRequest,
)
from app.application.rag.service import RagChatService

router = APIRouter(prefix="/api/rag-chat/sessions", tags=["RAG 问答"])


@router.post("", response_model=Result[RagSessionDTO])
async def create_session(
    body: CreateRagSessionRequest,
    service: RagChatService = Depends(get_rag_chat_service),
) -> Result[RagSessionDTO]:
    data = await service.create_session(body.knowledge_base_ids, body.title)
    return Result.success(data=data)


@router.get("", response_model=Result[list[RagSessionListItemDTO]])
async def list_sessions(
    service: RagChatService = Depends(get_rag_chat_service),
) -> Result[list[RagSessionListItemDTO]]:
    data = await service.list_sessions()
    return Result.success(data=data)


@router.get("/{session_id}", response_model=Result[RagSessionDetailDTO])
async def get_session(
    session_id: int,
    service: RagChatService = Depends(get_rag_chat_service),
) -> Result[RagSessionDetailDTO]:
    data = await service.get_detail(session_id)
    return Result.success(data=data)


@router.put("/{session_id}/title", response_model=Result[None])
async def update_session_title(
    session_id: int,
    body: UpdateTitleRequest,
    service: RagChatService = Depends(get_rag_chat_service),
) -> Result[None]:
    await service.update_title(session_id, body.title)
    return Result.success(data=None)


@router.put("/{session_id}/pin", response_model=Result[None])
async def toggle_pin(
    session_id: int,
    service: RagChatService = Depends(get_rag_chat_service),
) -> Result[None]:
    await service.toggle_pin(session_id)
    return Result.success(data=None)


@router.delete("/{session_id}")
async def delete_session(
    session_id: int,
    service: RagChatService = Depends(get_rag_chat_service),
) -> Result[None]:
    await service.delete(session_id)
    return Result.success(data=None)


@router.post("/{session_id}/messages/stream")
@limiter.limit("5/second", key_func=global_key)
@limiter.limit("5/second")
async def send_message_stream(
    request: Request,  # noqa: ARG001  slowapi 限流必需
    session_id: int,
    body: SendMessageRequest,
    service: RagChatService = Depends(get_rag_chat_service),
) -> StreamingResponse:
    return StreamingResponse(
        service.stream_query(session_id, body.question),
        media_type="text/event-stream",
    )
