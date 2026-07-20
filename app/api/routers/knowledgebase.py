from fastapi import APIRouter, Depends, File, Query, Request, UploadFile

from app.api.deps import get_knowledge_base_service
from app.api.rate_limit import global_key, limiter
from app.api.responses import Result
from app.application.knowledgebase.schemas import (
    KnowledgeBaseDetailDTO,
    KnowledgeBasePageDTO,
    KnowledgeBaseUploadResponse,
)
from app.application.knowledgebase.service import KnowledgeBaseService

router = APIRouter(prefix="/api/knowledge-bases", tags=["知识库管理"])


@router.post("/upload", response_model=Result[KnowledgeBaseUploadResponse])
@limiter.limit("3/second", key_func=global_key)
@limiter.limit("3/second")
async def upload_knowledge_base(
    request: Request,  # noqa: ARG001  slowapi 限流必需
    file: UploadFile = File(...),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[KnowledgeBaseUploadResponse]:
    data = await file.read()
    filename = file.filename or "unknown"
    content_type = file.content_type or ""
    result = await service.upload(filename, content_type, data)
    return Result.success(data=result)


@router.get("", response_model=Result[KnowledgeBasePageDTO])
async def list_knowledge_bases(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[KnowledgeBasePageDTO]:
    result = await service.list_knowledge_bases(page=page, size=size)
    return Result.success(data=result)


@router.get("/{kb_id}/detail", response_model=Result[KnowledgeBaseDetailDTO])
async def get_knowledge_base_detail(
    kb_id: int,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[KnowledgeBaseDetailDTO]:
    result = await service.get_detail(kb_id)
    return Result.success(data=result)


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: int,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[None]:
    await service.delete(kb_id)
    return Result.success(data=None)


@router.post("/{kb_id}/revectorize")
@limiter.limit("2/second", key_func=global_key)
@limiter.limit("2/second")
async def revectorize_knowledge_base(
    request: Request,  # noqa: ARG001  slowapi 限流必需
    kb_id: int,
    service: KnowledgeBaseService = Depends(get_knowledge_base_service),
) -> Result[None]:
    await service.revectorize(kb_id)
    return Result.success(data=None)
